# pagos/views.py
import logging
import hashlib
import requests
import json
import decimal
from datetime import timedelta
from urllib.parse import urlencode

import mercadopago
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from emails.utils import send_brevo_email

from packages.models import Purchase
from .models import Payment, PaymentMethod
from .serializers import PaymentSerializer, PaymentMethodSerializer

logger = logging.getLogger(__name__)

# Formatear moneda para el correo
def format_currency(amount):
    try:
        amount_decimal = decimal.Decimal(str(amount))
        return "${:,.0f} COP".format(amount_decimal)
    except (decimal.InvalidOperation, TypeError):
        return "$0 COP"

# --- Vistas de Métodos de Pago y Historial ---
class PaymentMethodListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Lista los métodos de pago del usuario (si los hay)."""
        logger.info(f"[PaymentMethodListView] Solicitud de métodos de pago por {request.user.email}")
        methods = PaymentMethod.objects.filter(user=request.user).order_by('-created_at')
        serializer = PaymentMethodSerializer(methods, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class PaymentHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Obtiene el historial de pagos (Payment) del usuario."""
        try:
            payments = Payment.objects.filter(user=request.user).order_by('-created_at')
            serializer = PaymentSerializer(payments, many=True)
            logger.info(f"[PaymentHistoryView] Historial de pagos obtenido para {request.user.email}")
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"[PaymentHistoryView] Error obteniendo historial para {request.user.email}: {str(e)}", exc_info=True)
            return Response({"error": "Error al obtener historial de pagos"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- Vista para Iniciar Checkout ---
class InitiateCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_webhook_url(self, request, webhook_name):
        """Genera la URL del webhook."""
        try:
            webhook_relative_path = reverse(webhook_name)
            if hasattr(settings, 'PUBLIC_BACKEND_URL') and settings.PUBLIC_BACKEND_URL:
                return f"{settings.PUBLIC_BACKEND_URL.rstrip('/')}{webhook_relative_path}"
            absolute_uri = request.build_absolute_uri(webhook_relative_path)
            logger.warning(f"PUBLIC_BACKEND_URL no configurada. Usando build_absolute_uri: {absolute_uri}")
            return absolute_uri
        except Exception as e:
            logger.error(f"Error generando URL para webhook '{webhook_name}': {e}", exc_info=True)
            raise ValueError(f"No se pudo generar URL de notificación: {e}")

    def _prepare_payu_checkout(self, request, purchase):
        """Prepara los datos para el checkout de PayU."""
        try:
            reference_code = purchase.reference_code
            price_decimal = purchase.final_price
            amount_str = str(price_decimal.quantize(decimal.Decimal('0.01')))
            tax_str = "0"
            tax_return_base_str = "0"
            currency = "COP"

            response_url = f"{settings.FRONTEND_URL}/dashboard/payment-response/"
            confirmation_url = self._get_webhook_url(request, 'pagos:webhook-payu')

            description = f"Compra de {purchase.purchased_session_count} sesiones ({purchase.therapy_type_purchased})"

            signature_string = f"{settings.PAYU_API_KEY}~{settings.PAYU_MERCHANT_ID}~{reference_code}~{amount_str}~{currency}"
            signature = hashlib.md5(signature_string.encode()).hexdigest()

            payu_checkout_data = {
                "merchantId": settings.PAYU_MERCHANT_ID,
                "accountId": settings.PAYU_ACCOUNT_ID,
                "description": description,
                "referenceCode": reference_code,
                "amount": amount_str,
                "tax": tax_str,
                "taxReturnBase": tax_return_base_str,
                "currency": currency,
                "signature": signature,
                "test": "1" if settings.PAYU_TEST else "0",
                "buyerEmail": purchase.user.email,
                "buyerFullName": purchase.user.get_full_name() or purchase.user.email.split('@')[0],
                "responseUrl": response_url,
                "confirmationUrl": confirmation_url,
            }
            payu_checkout_url = (
                "https://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/" if settings.PAYU_TEST
                else "https://checkout.payulatam.com/ppp-web-gateway-payu/"
            )
            logger.info(f"[PayU] Checkout preparado para {reference_code} por ${amount_str} {currency}")
            return Response(
                {"provider": "PAYU", "payu_checkout_url": payu_checkout_url, "payu_checkout_data": payu_checkout_data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"[PayU] Error preparando checkout para {purchase.reference_code}: {str(e)}", exc_info=True)
            raise

    def _prepare_mercadopago_checkout(self, request, purchase):
        """Prepara los datos para el checkout de Mercado Pago."""
        try:
            reference_code = purchase.reference_code
            if not settings.MP_ACCESS_TOKEN:
                raise ValueError("MP_ACCESS_TOKEN no configurado")
            sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)

            notification_url = self._get_webhook_url(request, 'pagos:webhook-mercadopago')
            base_response_url = f"{settings.FRONTEND_URL}/payment-response/"
            back_urls = {
                "success": f"{base_response_url}?status=success&ref={reference_code}",
                "failure": f"{base_response_url}?status=failure&ref={reference_code}",
                "pending": f"{base_response_url}?status=pending&ref={reference_code}"
            }

            item_title = f"{purchase.purchased_session_count} sesiones ({purchase.therapy_type_purchased})"
            item_id = f"SESSIONS-{purchase.therapy_type_purchased}-{purchase.purchased_session_count}-{purchase.id}"
            item_price = float(purchase.final_price)

            preference_data = {
                "items": [
                    {
                        "id": item_id[:256],
                        "title": item_title[:256],
                        "quantity": 1,
                        "currency_id": "COP",
                        "unit_price": item_price
                    }
                ],
                "payer": {
                    "name": purchase.user.first_name or 'Usuario',
                    "surname": purchase.user.last_name or 'PsicoApp',
                    "email": purchase.user.email
                },
                "back_urls": back_urls,
                "notification_url": notification_url,
                "external_reference": reference_code,
                "auto_return": "approved",
            }

            preference_response = sdk.preference().create(preference_data)
            if preference_response["status"] >= 300:
                error_msg = preference_response.get("response", {}).get('message', 'Error desconocido')
                logger.error(f"[MP] Error creando preferencia: {error_msg}")
                raise ValueError(f"Error de Mercado Pago: {error_msg}")

            preference = preference_response["response"]
            preference_id = preference["id"]
            checkout_url = preference.get("sandbox_init_point" if settings.MP_SANDBOX_MODE else "init_point")

            logger.info(f"[MP] Preferencia {preference_id} creada para {reference_code}")
            return Response(
                {
                    "provider": "MERCADOPAGO",
                    "preference_id": preference_id,
                    "public_key": settings.MP_PUBLIC_KEY,
                    "checkout_url": checkout_url,
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"[MP] Error preparando checkout para {purchase.reference_code}: {str(e)}", exc_info=True)
            raise

    def post(self, request):
        """Inicia el proceso de checkout para una compra."""
        user = request.user
        purchase_id = request.data.get('purchase_id')

        if not purchase_id:
            return Response({'error': 'Se requiere purchase_id'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            purchase = Purchase.objects.select_related('user', 'terapia', 'discount_code').get(
                id=purchase_id,
                user=user,
                payment_status='pending'
            )
            logger.info(f"Iniciando checkout para Purchase ID: {purchase.id}, Ref: {purchase.reference_code} por {user.email}")
        except Purchase.DoesNotExist:
            logger.warning(f"Compra no válida (ID: {purchase_id}) para {user.email}")
            return Response({'error': 'Compra no encontrada o no válida'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error buscando Purchase ID {purchase_id}: {e}", exc_info=True)
            return Response({'error': 'Error al buscar la compra'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            active_provider = getattr(settings, 'ACTIVE_PAYMENT_PROVIDER', 'PAYU').upper()
            if active_provider == 'MERCADOPAGO':
                return self._prepare_mercadopago_checkout(request, purchase)
            elif active_provider == 'PAYU':
                return self._prepare_payu_checkout(request, purchase)
            else:
                logger.error(f"Proveedor desconocido: {active_provider}")
                raise ValueError("Proveedor de pago no configurado correctamente")
        except Exception as e:
            error_message = 'No se pudo iniciar el proceso de pago. Intenta de nuevo más tarde.'
            if isinstance(e, ValueError) and "configurado" in str(e):
                error_message = "Problema de configuración del sistema de pago. Contacta a soporte."
            
            try:
                purchase.update_payment_status(
                    new_status='failed',
                    error=f"Error preparando checkout: {str(e)}"
                )
            except Exception as update_err:
                logger.error(f"Error marcando compra como fallida: {update_err}", exc_info=True)
                purchase.payment_status = 'failed'
                purchase.error_message = f"Error preparando checkout: {str(e)}"
                purchase.save()
            
            logger.error(f"Error en checkout para {purchase.reference_code}: {e}", exc_info=True)
            return Response({'error': error_message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- Webhook PayU ---
@method_decorator(csrf_exempt, name='dispatch')
class WebhookPayUView(APIView):
    permission_classes = [AllowAny]

    def _validate_payu_signature(self, data):
        """Valida la firma de PayU."""
        required = ['reference_sale', 'state_pol', 'value', 'currency', 'sign']
        if not all(data.get(k) for k in required):
            return False, "Datos incompletos"

        try:
            formatted_value = "{:.2f}".format(decimal.Decimal(data['value']))
            signature_string = f"{settings.PAYU_API_KEY}~{settings.PAYU_MERCHANT_ID}~{data['reference_sale']}~{formatted_value}~{data['currency']}~{data['state_pol']}"
            calculated_signature = hashlib.md5(signature_string.encode()).hexdigest()
            return calculated_signature.lower() == data['sign'].lower(), "Firma válida" if calculated_signature.lower() == data['sign'].lower() else "Firma inválida"
        except Exception as e:
            logger.error(f"Error validando firma PayU: {e}", exc_info=True)
            return False, "Error validando firma"

    def post(self, request):
        """Procesa notificaciones de PayU."""
        data = request.POST
        logger.info(f"[PayU] Webhook recibido: {data.dict()}")

        reference_sale = data.get('reference_sale')
        if not reference_sale:
            logger.error("[PayU] Webhook sin reference_sale")
            return Response({"status": "ok", "message": "Sin reference_sale"}, status=status.HTTP_200_OK)

        is_valid, message = self._validate_payu_signature(data)
        if not is_valid:
            logger.error(f"[PayU] {reference_sale}: {message}")
            return Response({"status": "ok", "message": message}, status=status.HTTP_200_OK)

        try:
            purchase = Purchase.objects.get(reference_code=reference_sale)
        except Purchase.DoesNotExist:
            logger.error(f"[PayU] {reference_sale}: Compra no encontrada")
            return Response({"status": "ok", "message": "Compra no encontrada"}, status=status.HTTP_200_OK)

        if purchase.payment_status in ['completed', 'failed', 'refunded']:
            logger.info(f"[PayU] {reference_sale}: Ya en estado final '{purchase.payment_status}'")
            return Response({"status": "ok", "message": "Estado final"}, status=status.HTTP_200_OK)

        state_pol = data.get('state_pol')
        transaction_id = data.get('transaction_id')
        payment_details = {
            'method': data.get('payment_method_name'),
            'type': data.get('payment_method_type'),
            'last_four': data.get('cc_number', '')[-4:] if data.get('cc_number') else None
        }

        new_status = 'pending'
        error_msg = None
        if state_pol == '4':
            new_status = 'completed'
        elif state_pol in ['6', '5']:
            new_status = 'failed'
            error_msg = data.get('response_message_pol', 'Transacción Declinada/Expirada')
        elif state_pol == '7':
            error_msg = data.get('response_message_pol', 'Transacción Pendiente')

        try:
            purchase.update_payment_status(
                new_status=new_status,
                provider='payu',
                transaction_id=transaction_id,
                details=data.dict(),
                error=error_msg
            )
            logger.info(f"[PayU] {reference_sale}: Actualizado a '{new_status}'")

            # Enviar correo de confirmación si la compra está completada
            if new_status == 'completed':
                context = {
                    'nombre': purchase.user.nombre or purchase.user.email.split('@')[0],
                    'reference_code': purchase.reference_code,
                    'therapy_type': purchase.therapy_type_purchased.capitalize(),
                    'session_count': purchase.purchased_session_count,
                    'price_per_session': format_currency(purchase.final_price / purchase.purchased_session_count),
                    'discount_applied': bool(purchase.discount_code),
                    'discount_amount': format_currency(purchase.discount_amount) if purchase.discount_code else None,
                    'discount_code': purchase.discount_code.code if purchase.discount_code else None,
                    'total_amount': format_currency(purchase.final_price),
                    'purchase_date': purchase.purchase_date.strftime('%d/%m/%Y %H:%M'),
                    'is_shared_therapy': purchase.terapia and purchase.therapy_type_purchased in ['pareja', 'familiar'],
                    'dashboard_url': f"{settings.FRONTEND_URL}/dashboard",
                    'support_email': settings.DEFAULT_FROM_EMAIL,
                    'year': timezone.now().year,
                }
                success = send_brevo_email(
                    subject="Confirmación de tu Compra - Senti",
                    to_email=purchase.user.email,
                    template_name="purchase_confirmation_email.html",
                    context=context
                )
                if success:
                    logger.info(f"[PayU] Correo de confirmación enviado a {purchase.user.email} para {reference_sale}")
                else:
                    logger.error(f"[PayU] Error enviando correo de confirmación a {purchase.user.email} para {reference_sale}")

        except Exception as e:
            logger.error(f"[PayU] {reference_sale}: Error actualizando: {e}", exc_info=True)
            return Response({"status": "error", "message": "Error actualizando"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"status": "success", "message": "Webhook procesado"}, status=status.HTTP_200_OK)


# --- Webhook Mercado Pago ---
@method_decorator(csrf_exempt, name='dispatch')
class WebhookMercadoPagoView(APIView):
    permission_classes = [AllowAny]

    def _get_payment_info(self, payment_id):
        """Obtiene información del pago desde Mercado Pago."""
        try:
            sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)
            response = sdk.payment().get(payment_id)
            if response["status"] >= 300:
                logger.error(f"[MP] Error obteniendo pago {payment_id}: {response.get('response')}")
                return None, "Error API MP"
            return response["response"], None
        except Exception as e:
            logger.error(f"[MP] Error API MP para {payment_id}: {e}", exc_info=True)
            return None, "Error al contactar MP"

    def post(self, request):
        """Procesa notificaciones de Mercado Pago."""
        data = request.data
        logger.info(f"[MP] Webhook recibido: {json.dumps(data)}")

        payment_id = data.get("data", {}).get("id") if data.get("type") == "payment" else None
        if not payment_id:
            logger.info("[MP] Webhook ignorado (no es payment)")
            return HttpResponse(status=200)

        payment_info, error = self._get_payment_info(payment_id)
        if error:
            return HttpResponse(status=200)

        external_reference = payment_info.get("external_reference")
        if not external_reference:
            logger.error(f"[MP] Pago {payment_id} sin external_reference")
            return HttpResponse(status=200)

        try:
            purchase = Purchase.objects.get(reference_code=external_reference)
        except Purchase.DoesNotExist:
            logger.error(f"[MP] {external_reference}: Compra no encontrada")
            return HttpResponse(status=200)

        if purchase.payment_status in ['completed', 'failed', 'refunded']:
            logger.info(f"[MP] {external_reference}: Ya en estado final '{purchase.payment_status}'")
            return HttpResponse(status=200)

        mp_status = payment_info.get("status")
        new_status = 'pending'
        error_msg = None
        if mp_status == 'approved':
            new_status = 'completed'
        elif mp_status in ['rejected', 'cancelled', 'refunded', 'charged_back']:
            new_status = 'failed'
            error_msg = f"MP Status: {mp_status} ({payment_info.get('status_detail')})"
        elif mp_status in ['in_process', 'pending', 'authorized']:
            error_msg = f"MP Status: {mp_status} ({payment_info.get('status_detail')})"

        try:
            purchase.update_payment_status(
                new_status=new_status,
                provider='mercadopago',
                transaction_id=str(payment_id),
                details=payment_info,
                error=error_msg
            )
            logger.info(f"[MP] {external_reference}: Actualizado a '{new_status}'")

            # Enviar correo de confirmación si la compra está completada
            if new_status == 'completed':
                context = {
                    'nombre': purchase.user.nombre or purchase.user.email.split('@')[0],
                    'reference_code': purchase.reference_code,
                    'therapy_type': purchase.therapy_type_purchased.capitalize(),
                    'session_count': purchase.purchased_session_count,
                    'price_per_session': format_currency(purchase.final_price / purchase.purchased_session_count),
                    'discount_applied': bool(purchase.discount_code),
                    'discount_amount': format_currency(purchase.discount_amount) if purchase.discount_code else None,
                    'discount_code': purchase.discount_code.code if purchase.discount_code else None,
                    'total_amount': format_currency(purchase.final_price),
                    'purchase_date': purchase.purchase_date.strftime('%d/%m/%Y %H:%M'),
                    'is_shared_therapy': purchase.terapia and purchase.therapy_type_purchased in ['pareja', 'familiar'],
                    'dashboard_url': f"{settings.FRONTEND_URL}/dashboard",
                    'support_email': settings.DEFAULT_FROM_EMAIL,
                    'year': timezone.now().year,
                }
                success = send_brevo_email(
                    subject="Confirmación de tu Compra - Senti",
                    to_email=purchase.user.email,
                    template_name="purchase_confirmation_email.html",
                    context=context
                )
                if success:
                    logger.info(f"[MP] Correo de confirmación enviado a {purchase.user.email} para {external_reference}")
                else:
                    logger.error(f"[MP] Error enviando correo de confirmación a {purchase.user.email} para {external_reference}")

        except Exception as e:
            logger.error(f"[MP] {external_reference}: Error actualizando: {e}", exc_info=True)
            return HttpResponse(status=500)

        return HttpResponse(status=200)

# --- Vistas de Reembolso ---
class RefundView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Procesa reembolsos automáticos."""
        transaction_id = request.data.get('transaction_id')
        if not transaction_id:
            return Response({"error": "Se requiere transaction_id"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            purchase = Purchase.objects.get(transaction_id=transaction_id, user=request.user)
            logger.info(f"[Refund] Intento de reembolso para {purchase.reference_code} por {request.user.email}")
        except Purchase.DoesNotExist:
            logger.warning(f"[Refund] Compra con TxID {transaction_id} no encontrada")
            return Response({"error": "Compra no encontrada"}, status=status.HTTP_404_NOT_FOUND)

        if purchase.payment_status != 'completed':
            return Response({"error": "Solo compras completadas pueden ser reembolsadas"}, status=status.HTTP_400_BAD_REQUEST)

        refund_window_hours = getattr(settings, 'AUTO_REFUND_WINDOW_HOURS', 24)
        if timezone.now() - purchase.purchase_date > timedelta(hours=refund_window_hours):
            return Response({"error": f"Reembolso disponible solo dentro de {refund_window_hours} horas"}, status=status.HTTP_400_BAD_REQUEST)

        provider = purchase.payment_provider
        try:
            if provider == 'payu':
                payload = {
                    "test": settings.PAYU_TEST,
                    "language": "es",
                    "command": "SUBMIT_TRANSACTION",
                    "merchant": {"apiLogin": settings.PAYU_API_LOGIN, "apiKey": settings.PAYU_API_KEY},
                    "transaction": {
                        "type": "REFUND",
                        "parentTransactionId": transaction_id,
                        "orderId": purchase.reference_code,
                        "reason": "Reembolso automático"
                    }
                }
                response = requests.post(
                    "https://sandbox.api.payulatam.com/payments-api/4.0/service.cgi" if settings.PAYU_TEST else "https://api.payulatam.com/payments-api/4.0/service.cgi",
                    json=payload,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    timeout=30
                )
                response_data = response.json()
                if response_data.get('code') == 'SUCCESS' and response_data.get('transactionResponse', {}).get('state') == 'APPROVED':
                    purchase.update_payment_status('refunded', details={'refund_response': response_data})
                    logger.info(f"[PayU Refund] Reembolso exitoso para {purchase.reference_code}")
                    return Response({"message": "Reembolso procesado"}, status=status.HTTP_200_OK)
                else:
                    logger.error(f"[PayU Refund] Error: {response_data}")
                    return Response({"error": "Reembolso rechazado por PayU"}, status=status.HTTP_400_BAD_REQUEST)

            elif provider == 'mercadopago':
                sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)
                refund_response = sdk.refund().create(transaction_id, {})
                if refund_response["status"] in [200, 201]:
                    purchase.update_payment_status('refunded', details={'refund_response': refund_response["response"]})
                    logger.info(f"[MP Refund] Reembolso exitoso para {purchase.reference_code}")
                    return Response({"message": "Reembolso procesado"}, status=status.HTTP_200_OK)
                else:
                    logger.error(f"[MP Refund] Error: {refund_response}")
                    return Response({"error": "Reembolso rechazado por Mercado Pago"}, status=status.HTTP_400_BAD_REQUEST)

            else:
                return Response({"error": f"Reembolsos no soportados para {provider}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"[Refund] Error procesando reembolso para {transaction_id}: {e}", exc_info=True)
            return Response({"error": "Error procesando reembolso"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RequestRefundSupportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Solicita soporte para reembolso manual."""
        transaction_id = request.data.get('transaction_id')
        message = request.data.get('message')

        if not transaction_id or not message:
            return Response({"error": "Se requiere transaction_id y message"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            purchase = Purchase.objects.get(transaction_id=transaction_id, user=request.user)
            subject = f"Solicitud Reembolso - Ref: {purchase.reference_code}"
            body = f"Usuario: {request.user.email}\nCompra: {purchase.reference_code}\nMotivo: {message}"
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [settings.SUPPORT_EMAIL])
            logger.info(f"[Refund Support] Solicitud enviada para {purchase.reference_code}")
            return Response({"message": "Solicitud enviada a soporte"}, status=status.HTTP_200_OK)
        except Purchase.DoesNotExist:
            return Response({"error": "Compra no encontrada"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"[Refund Support] Error enviando solicitud: {e}", exc_info=True)
            return Response({"error": "Error enviando solicitud"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
import decimal
from django.db import models
from django.conf import settings
from api.models import Terapia # Asegúrate que esta importación sea correcta y Terapia esté definida en api.models
from django.utils import timezone
from django.core.exceptions import ValidationError
from pagos.models import Payment # Asegúrate que esta importación sea correcta y Payment esté definida en pagos.models
import logging

logger = logging.getLogger(__name__)

class DiscountCode(models.Model):
    code = models.CharField(max_length=20, unique=True)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    uses = models.PositiveIntegerField(default=0)

    def is_valid(self):
        # Verifica primero si está activo
        if not self.is_active:
            return False, "El código de descuento está inactivo."

        # Verifica la fecha de expiración (si existe)
        if self.valid_until and self.valid_until < timezone.now():
            # Si valid_until es anterior a ahora, el código ha expirado.
            return False, "El código de descuento ha expirado."

        # Verifica el límite de usos (si existe)
        if self.max_uses is not None and self.uses >= self.max_uses:
            return False, "Este código de descuento ha alcanzado su límite de usos."

        # Si pasó todas las validaciones
        return True, "" # Retorna True y un string vacío para "sin error"

    def __str__(self):
        return f"{self.code} ({self.discount_percentage}% off)"

class SessionPricingTier(models.Model):
    therapy_type = models.CharField(max_length=50, db_index=True)
    min_sessions = models.PositiveIntegerField(default=1)
    max_sessions = models.PositiveIntegerField(null=True, blank=True)
    price_per_session = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['therapy_type', 'min_sessions']
        constraints = [
            models.UniqueConstraint(fields=['therapy_type', 'min_sessions'], name='unique_tier_start')
        ]

    def clean(self):
        if self.max_sessions is not None and self.min_sessions > self.max_sessions:
            raise ValidationError("La cantidad mínima no puede ser mayor que la máxima.")

    def __str__(self):
        session_range = f"{self.min_sessions}"
        if self.max_sessions:
            session_range += f"-{self.max_sessions}"
        else:
            session_range += "+"
        return f"{self.therapy_type.capitalize()} ({session_range} sesiones): ${self.price_per_session}/sesión"

class Purchase(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='package_purchases')
    terapia = models.ForeignKey(Terapia, on_delete=models.CASCADE, null=True, blank=True, related_name='purchases')
    therapy_type_purchased = models.CharField(max_length=50)
    purchased_session_count = models.PositiveIntegerField()
    price_per_session_applied = models.DecimalField(max_digits=10, decimal_places=2)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_code = models.ForeignKey(DiscountCode, on_delete=models.SET_NULL, null=True, blank=True)
    discount_applied_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    final_price = models.DecimalField(max_digits=10, decimal_places=2)
    purchase_date = models.DateTimeField(auto_now_add=True)
    payment_status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pendiente'), ('completed', 'Completado'), ('failed', 'Fallido'), ('refunded', 'Reembolsado')],
        default='pending'
    )
    remaining_sessions = models.PositiveIntegerField(default=0)
    reference_code = models.CharField(max_length=100, unique=True)
    transaction_id = models.CharField(max_length=255, blank=True, null=True)
    payment_provider = models.CharField(max_length=50, blank=True, null=True)
    payment_details = models.JSONField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    currency = models.CharField(max_length=3, default='COP')

    def __str__(self):
        user_display = getattr(self.user, 'email', None) or str(self.user.pk)
        terapia_display = f" para Terapia {self.terapia.id}" if self.terapia else f" ({self.therapy_type_purchased})"
        return f"Compra {self.purchased_session_count} sesiones por {user_display}{terapia_display} - Estado: {self.payment_status}"

    def update_payment_status(self, new_status, provider=None, transaction_id=None, details=None, error=None):
        self.payment_status = new_status
        if provider:
            self.payment_provider = provider
        if transaction_id:
            self.transaction_id = transaction_id
        if details is not None:
            self.payment_details = details if isinstance(details, dict) else {}
        if error is not None:
            self.error_message = error

        if new_status == 'completed':
            # Solo actualiza remaining_sessions si es una compra nueva que se completa,
            # o si por alguna razón se estaba reintentando un pago y remaining_sessions era 0.
            if self.remaining_sessions == 0:
                self.remaining_sessions = self.purchased_session_count
        elif new_status in ['failed', 'refunded']:
            self.remaining_sessions = 0

        update_fields = ['payment_status', 'remaining_sessions']
        if provider: update_fields.append('payment_provider')
        if transaction_id: update_fields.append('transaction_id')
        if details is not None: update_fields.append('payment_details')
        if error is not None: update_fields.append('error_message')

        self.save(update_fields=update_fields)
        logger.info(f"Purchase {self.reference_code} actualizada a estado: {self.payment_status}. Campos actualizados: {update_fields}")

        if new_status == 'completed' and self.final_price > 0 and transaction_id:
            try:
                payment_method_details = self.payment_details or {}
                method_description = "Desconocido"
                card_last_four = None

                if self.payment_provider == 'payu':
                    method_description = payment_method_details.get('payment_method_name', 'PayU')
                    cc_num = payment_method_details.get('cc_number')
                    if cc_num and isinstance(cc_num, str) and len(cc_num) >= 4:
                         card_last_four = cc_num[-4:]
                elif self.payment_provider == 'mercadopago':
                    method_description = payment_method_details.get('payment_method', {}).get('name', payment_method_details.get('payment_type_id', 'MercadoPago'))
                    card_info = payment_method_details.get('card', {})
                    card_last_four = card_info.get('last_four_digits')

                payment_description = f"Compra {self.reference_code} ({self.purchased_session_count} sesiones {self.therapy_type_purchased})"

                payment_obj, created = Payment.objects.update_or_create(
                    transaction_id=transaction_id,
                    provider=self.payment_provider,
                    defaults={
                        'user': self.user,
                        'purchase': self, # Asumiendo que Payment tiene un FK a Purchase
                        'amount': self.final_price,
                        'currency': self.currency,
                        'status': 'completed',
                        'method': method_description,
                        'card_last_four': card_last_four,
                        'description': payment_description,
                    }
                )
                if created:
                    logger.info(f"Registro Payment CREADO para TxID {transaction_id} (Compra {self.reference_code})")
                else:
                     logger.info(f"Registro Payment ACTUALIZADO para TxID {transaction_id} (Compra {self.reference_code})")
            except Exception as e:
                logger.error(f"Error al crear/actualizar registro Payment para TxID {transaction_id} (Compra {self.reference_code}): {e}", exc_info=True)

    @staticmethod
    def calculate_price(therapy_type, session_count, discount_code_obj=None): # Cambiado a discount_code_obj
        # import decimal # Ya está importado al inicio del archivo
        # from django.utils import timezone # Ya está importado al inicio del archivo
        # from .models import SessionPricingTier, DiscountCode # Evitar importación circular si se llama desde el mismo módulo
        # import logging # Ya está importado al inicio del archivo

        # logger = logging.getLogger(__name__) # Ya está definido globalmente

        if not isinstance(session_count, int) or session_count <= 0:
            # Levantar un error más específico si es posible, o dejarlo como ValueError
            raise ValueError("El número de sesiones debe ser un entero positivo.")

        tiers = SessionPricingTier.objects.filter(
            therapy_type=therapy_type,
            min_sessions__lte=session_count,
            is_active=True
        ).order_by('-min_sessions')

        if not tiers.exists():
            raise ValueError(f"No se encontró un tier de precios activo para {therapy_type} con {session_count} sesiones.")

        tier = tiers.first()
        # logger.debug(f"Tier seleccionado para {therapy_type}: min_sessions={tier.min_sessions}, price_per_session={tier.price_per_session}")

        if tier.max_sessions and session_count > tier.max_sessions:
            raise ValueError(f"El número de sesiones ({session_count}) excede el máximo permitido ({tier.max_sessions}) para este tier.")

        price_per_session = tier.price_per_session
        if not isinstance(price_per_session, decimal.Decimal):
            price_per_session = decimal.Decimal(str(price_per_session))
        # logger.debug(f"Price per session: {price_per_session}")

        base_price = price_per_session * decimal.Decimal(session_count)
        # logger.debug(f"Base price: {base_price}")

        discount_percentage = decimal.Decimal('0.00')
        discount_amount = decimal.Decimal('0.00')
        discount_error = None
        applied_discount_code_for_return = None # El objeto código de descuento a retornar

        if discount_code_obj: # Ahora espera un objeto DiscountCode o None
            # No necesitamos hacer DiscountCode.objects.get() aquí, ya tenemos el objeto.
            # La validación (is_active, valid_until, max_uses) se hace ANTES de llamar a calculate_price, en el serializer.
            # Aquí solo aplicamos el porcentaje si el objeto existe.
            is_valid, error_msg = discount_code_obj.is_valid() # Re-chequeo por si acaso o si la lógica cambia
            if is_valid:
                discount_percentage = discount_code_obj.discount_percentage
                if not isinstance(discount_percentage, decimal.Decimal):
                    discount_percentage = decimal.Decimal(str(discount_percentage))
                discount_amount = (base_price * discount_percentage) / decimal.Decimal('100')
                applied_discount_code_for_return = discount_code_obj # Guardamos el objeto para retornarlo
                # logger.debug(f"Descuento aplicado: {discount_percentage}%, Monto: {discount_amount}")
            else:
                # Si por alguna razón el código que se pasó no es válido,
                # seteamos el error. El serializador debería haberlo atrapado antes.
                discount_error = error_msg
        # else: No se proporcionó ningún objeto de código de descuento

        final_price = base_price - discount_amount
        # logger.debug(f"Final price calculado: {final_price}")

        # La validación de final_price <= 0 podría hacerse también en el serializador
        # después de llamar a calculate_price, para un control más centralizado.
        # Pero si se deja aquí, también está bien.
        if final_price < 0: # Permitir 0, pero no negativo
            final_price = decimal.Decimal('0.00') # Opcional: Forzar a 0 si es negativo
            # O podrías lanzar un error si un precio negativo no tiene sentido:
            # raise ValueError(f"El precio final calculado es negativo ({final_price}), lo cual no es permitido.")

        return {
            "therapy_type": therapy_type,
            "session_count": session_count,
            "price_per_session": price_per_session,
            "base_price": base_price,
            "discount_code": applied_discount_code_for_return, # Devolver el objeto
            "discount_percentage": discount_percentage,
            "discount_amount": discount_amount,
            "final_price": final_price,
            "discount_error": discount_error # Este será None si todo fue bien con el descuento
        }
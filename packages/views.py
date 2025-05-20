# packages/views.py
import logging
import decimal # Importar decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status, serializers # NUEVO: Importar serializers para ValidationError
from django.db import models as django_models # Renombrar para evitar confusión con models.py
from django.utils import timezone
from django.db.models import Q # Importar Q para consultas complejas
import uuid # Importar uuid para generar códigos únicos
# Modelos actualizados
from .models import Purchase, DiscountCode, SessionPricingTier # , Package # Mantén Package si lo usas
# Serializers (Asegúrate que estos existen y están definidos correctamente)
from .serializers import (
    # PackageSerializer, # Si usas paquetes predefinidos
    PurchaseReadSerializer,
    PurchaseCreateSerializer,
    InitiatePurchaseResponseSerializer,
    SessionPricingTierSerializer,
)
# Asumiendo que PackageSerializer y Package existen si los necesitas:
# NOTA: La lógica para PACKAGE_MODEL_EXISTS y PackageSerializer
# parece estar definida dos veces. Me quedo con la segunda definición
# que los setea a None, ya que indicaste que no hay paquetes.
try:
    from .models import Package
    from .serializers import PackageSerializer
    # PACKAGE_MODEL_EXISTS = True # Comentado porque se redefine abajo
except ImportError:
    # PACKAGE_MODEL_EXISTS = False # Comentado
    pass # No es necesario redefinir Package y PackageSerializer aquí

from api.models import MiembroTerapia, Terapia # Modelos de tu app 'api'

PACKAGE_MODEL_EXISTS = False # Esto prevalece
Package = None
PackageSerializer = None
# SUGERENCIA: Mover la lógica de paginación a settings.py o un archivo de configuración
# from rest_framework.pagination import PageNumberPagination

logger = logging.getLogger(__name__)

# Vista para mostrar opciones de compra (Precios y Paquetes si existen)
class PricingOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        try:
            miembro_terapias = MiembroTerapia.objects.filter(usuario=user).select_related('terapia')
            user_therapy_types = set(miembro_terapias.values_list('terapia__tipo', flat=True).distinct())
        except Exception as e:
            logger.error(f"Error al obtener tipos de terapia para {user.email}: {e}", exc_info=True)
            user_therapy_types = set()

        try:
            pricing_tiers = SessionPricingTier.objects.filter(is_active=True).order_by('therapy_type', 'min_sessions')
            tier_serializer = SessionPricingTierSerializer(pricing_tiers, many=True)
            pricing_tiers_data = tier_serializer.data
        except Exception as e:
            logger.error(f"Error al obtener/serializar SessionPricingTiers: {e}", exc_info=True)
            return Response({'error': 'No se pudieron cargar las opciones de precios.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        predefined_packages_data = []  # No hay paquetes porque Package no existe

        return Response({
            "pricing_tiers": pricing_tiers_data,
            "predefined_packages": predefined_packages_data,
            "user_therapy_types": list(user_therapy_types)
        }, status=status.HTTP_200_OK)


# Vista para calcular precio SIN crear la compra (útil para el frontend)
class CalculatePriceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        therapy_type = request.data.get('therapy_type')
        session_count_str = request.data.get('session_count') # Obtener como string primero
        discount_code_str = request.data.get('discount_code', None)

        # Validación básica de entrada
        if not therapy_type:
             return Response({'error': "El campo 'therapy_type' es requerido."}, status=status.HTTP_400_BAD_REQUEST)
        if session_count_str is None:
             return Response({'error': "El campo 'session_count' es requerido."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            count = int(session_count_str)
            if count <= 0:
                raise ValueError("session_count debe ser positivo.")
        except (ValueError, TypeError):
             return Response({'error': "'session_count' debe ser un número entero positivo."}, status=status.HTTP_400_BAD_REQUEST)

        # --- Inicio: Convertir string de código a objeto DiscountCode ---
        discount_code_object_to_pass = None # Objeto que se pasará a calculate_price
        user_provided_code_for_response = None # String que el usuario envió, para la respuesta

        if discount_code_str:
            cleaned_discount_code_str = discount_code_str.strip() # Limpiar el string
            user_provided_code_for_response = cleaned_discount_code_str # Guardar para la respuesta
            if cleaned_discount_code_str: # Solo si después de limpiar no está vacío
                try:
                    # Intenta obtener el objeto DiscountCode basado en el string
                    temp_code_obj = DiscountCode.objects.get(
                        Q(valid_until__gte=timezone.now()) | Q(valid_until__isnull=True),
                        code=cleaned_discount_code_str,
                        is_active=True
                    )
                    # Verifica si el código es realmente válido usando su propio método
                    # El método is_valid() ya verifica is_active, valid_until, y max_uses
                    is_valid, _ = temp_code_obj.is_valid() # Ignoramos el mensaje de error aquí por ahora
                    if is_valid:
                        discount_code_object_to_pass = temp_code_obj
                    # Si no es válido según is_valid(), discount_code_object_to_pass permanecerá None.
                    # El método calculate_price en el modelo podrá generar un discount_error si es None.
                except DiscountCode.DoesNotExist:
                    # Si el código no existe o no cumple las condiciones iniciales del .get(),
                    # discount_code_object_to_pass permanecerá None.
                    # El método calculate_price en el modelo generará un discount_error.
                    pass # No es necesario hacer nada más aquí, calculate_price lo gestionará
        # --- Fin: Convertir string de código a objeto DiscountCode ---

        try:
             # Llamar al método estático del modelo para hacer el cálculo
             # Pasando el objeto DiscountCode (o None)
             result = Purchase.calculate_price(therapy_type, count, discount_code_object_to_pass)

             # Preparar respuesta amigable (convirtiendo Decimal a string para JSON)
             response_data = {
                 "therapy_type": result["therapy_type"],
                 "session_count": result["session_count"],
                 "price_per_session": str(result["price_per_session"]),
                 "base_price": str(result["base_price"]),
                 "discount_code_provided": user_provided_code_for_response, # El código que el usuario envió
                 "discount_code_applied": result["discount_code"].code if result.get("discount_code") else None, # El código que realmente se aplicó
                 "discount_percentage": str(result["discount_percentage"]),
                 "discount_applied_amount": str(result["discount_amount"]),
                 "final_price": str(result["final_price"]),
                 "calculation_message": "Precio calculado correctamente."
             }

             # Incluir el error del cupón si existió, para que el frontend lo muestre
             if result.get("discount_error"):
                 response_data["discount_error_message"] = result["discount_error"]
                 # Podrías también modificar calculation_message
                 response_data["calculation_message"] = f"Precio calculado. Nota sobre el cupón: {result['discount_error']}"
                 # Si hubo un error con el descuento, la respuesta podría ser 400 si así lo prefieres,
                 # o 200 con el mensaje de error. Actualmente es 200.
                 # Ejemplo si quieres 400 cuando hay discount_error:
                 # return Response(response_data, status=status.HTTP_400_BAD_REQUEST)


             return Response(response_data, status=status.HTTP_200_OK)

        except ValueError as e:
             logger.warning(f"Error de validación en cálculo de precio ({therapy_type}, {count}): {e}")
             return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
             logger.error(f"Error interno calculando precio para {therapy_type}, {count} sesiones: {e}", exc_info=True)
             return Response({'error': "Error interno al calcular el precio. Inténtalo de nuevo más tarde."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Vista REESCRITA para iniciar la compra (flexible o paquete)
class InitiatePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        logger.info(f"Intento de inicio de compra por {user.email}. Data: {request.data}")
        serializer = PurchaseCreateSerializer(data=request.data, context={'request': request})

        if serializer.is_valid():
            try:
                purchase = serializer.save() # El serializer ahora maneja la lógica del discount_code object
                
                # La validación de precio final > 0 ya se hace en el serializador (o debería)
                # Pero una doble verificación aquí no hace daño si quieres ser extra seguro.
                if purchase.final_price <= decimal.Decimal('0.00'): # Comparar con Decimal
                    # Esta lógica podría ser más robusta. ¿Se permite precio 0 si el descuento lo cubre?
                    # Si no, el serializador debería haberlo prevenido.
                    # Si se permite y aún así quieres borrarlo aquí, asegúrate de que el serializador no lo valide.
                    logger.warning(f"Compra (ID: {purchase.id}) creada con precio final {purchase.final_price}. Verificando si se debe borrar.")
                    # Considera la lógica: si el precio es 0 debido a un descuento completo, ¿es válido?
                    # Si no debe ser 0 en ningún caso, el serializador debería haber fallado.
                    # Si el serializador permite 0, entonces no deberías borrarlo aquí a menos que sea una condición excepcional.
                    # Por ahora, comentaré la eliminación para evitar borrar compras válidas de $0 con descuento.
                    # purchase.delete()
                    # logger.error(f"Compra creada con precio 0 inesperadamente y borrada: ID {purchase.id}")
                    # return Response({'error': 'El precio final debe ser mayor a cero (post-save check).'}, status=status.HTTP_400_BAD_REQUEST)


                # Verificar si es una terapia compartida y loguear la información
                if purchase.terapia and purchase.terapia.tipo in ['pareja', 'familiar']:
                    miembros = MiembroTerapia.objects.filter(terapia=purchase.terapia)
                    logger.info(f"Compra asociada a terapia compartida {purchase.terapia.id} con {miembros.count()} miembros. Todos pueden usar las {purchase.remaining_sessions} sesiones.")

                logger.info(f"Compra (ID: {purchase.id}, Ref: {purchase.reference_code}) creada para {user.email}. Precio final: {purchase.final_price}, Estado: {purchase.payment_status}")
                response_serializer = InitiatePurchaseResponseSerializer(purchase)
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            # No necesitas capturar serializers.ValidationError aquí si is_valid() ya lo hizo,
            # a menos que save() lance una ValidationError específica (menos común con ModelSerializer.save bien implementado)
            # except serializers.ValidationError as e:
            #     logger.warning(f"Error de validación durante save: {e.detail}")
            #     return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"Error inesperado al guardar la compra para {user.email}: {e}", exc_info=True)
                return Response({'error': 'Error al iniciar la compra.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            logger.warning(f"Error de validación del serializador para {user.email}: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Vista para listar las compras del usuario (usar el ReadSerializer)
class UserPurchasesView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        user = request.user

        # Compras donde el usuario es el 'comprador' O es miembro de la terapia asociada
        purchases_query = Purchase.objects.filter(
            Q(user=user) | Q(terapia__miembroterapia__usuario=user)
        ).filter(
            payment_status='completed' # Solo mostrar compras completadas
        ).distinct().order_by('-purchase_date')

        serializer = PurchaseReadSerializer(purchases_query, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
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
try:
    from .models import Package
    from .serializers import PackageSerializer
    PACKAGE_MODEL_EXISTS = True
except ImportError:
    PACKAGE_MODEL_EXISTS = False
    Package = None # Definir como None si no existe
    PackageSerializer = None # Definir como None si no existe


from api.models import MiembroTerapia, Terapia # Modelos de tu app 'api'

PACKAGE_MODEL_EXISTS = False
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
            return Response({'error': 'No se pudieron cargar las opciones de precios.'}, status=500)

        predefined_packages_data = []  # No hay paquetes porque Package no existe

        return Response({
            "pricing_tiers": pricing_tiers_data,
            "predefined_packages": predefined_packages_data,
            "user_therapy_types": list(user_therapy_types)
        }, status=200)


# Vista para calcular precio SIN crear la compra (útil para el frontend)
class CalculatePriceView(APIView):
    permission_classes = [IsAuthenticated]

    # SUGERENCIA: Podrías usar un serializer simple para validar la entrada aquí
    # class PriceCalculationInputSerializer(serializers.Serializer):
    #     therapy_type = serializers.CharField(required=True, max_length=50)
    #     session_count = serializers.IntegerField(required=True, min_value=1)
    #     discount_code = serializers.CharField(required=False, allow_blank=True, max_length=20)

    def post(self, request):
        therapy_type = request.data.get('therapy_type')
        session_count = request.data.get('session_count')
        discount_code = request.data.get('discount_code', None) # Obtener como None si no se envía

        # Validación básica de entrada
        if not therapy_type:
             return Response({'error': "El campo 'therapy_type' es requerido."}, status=status.HTTP_400_BAD_REQUEST)
        if session_count is None: # Verificar que se envió
             return Response({'error': "El campo 'session_count' es requerido."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            count = int(session_count)
            if count <= 0: raise ValueError()
        except (ValueError, TypeError):
             return Response({'error': "'session_count' debe ser un número entero positivo."}, status=status.HTTP_400_BAD_REQUEST)

        # Limpiar el código de descuento (opcional: quitar espacios, convertir a mayúsculas)
        cleaned_discount_code = discount_code.strip() if discount_code else None
        # cleaned_discount_code = discount_code.strip().upper() if discount_code else None

        try:
             # Llamar al método estático del modelo para hacer el cálculo
             result = Purchase.calculate_price(therapy_type, count, cleaned_discount_code)

             # Preparar respuesta amigable (convirtiendo Decimal a string para JSON)
             response_data = {
                 "therapy_type": result["therapy_type"],
                 "session_count": result["session_count"],
                 "price_per_session": str(result["price_per_session"]),
                 "base_price": str(result["base_price"]),
                 "discount_code_provided": cleaned_discount_code, # El código que el usuario envió
                 "discount_code_applied": result["discount_code"].code if result["discount_code"] else None, # El código que realmente se aplicó
                 "discount_percentage": str(result["discount_percentage"]),
                 "discount_applied_amount": str(result["discount_amount"]),
                 "final_price": str(result["final_price"]),
                 "calculation_message": "Precio calculado correctamente." if not result["discount_error"] else f"Precio calculado. Nota sobre el cupón: {result['discount_error']}"
             }
             # Incluir el error del cupón si existió, para que el frontend lo muestre
             if result["discount_error"]:
                 response_data["discount_error_message"] = result["discount_error"]

             return Response(response_data, status=status.HTTP_200_OK)

        except ValueError as e:
             # Errores específicos de la lógica de cálculo (ej. no hay tier, count inválido)
             logger.warning(f"Error de validación en cálculo de precio: {e}")
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
                purchase = serializer.save()
                if purchase.final_price <= 0:
                    purchase.delete()
                    logger.error(f"Compra creada con precio 0 inesperadamente: ID {purchase.id}")
                    return Response({'error': 'El precio final debe ser mayor a cero.'}, status=status.HTTP_400_BAD_REQUEST)

                # Verificar si es una terapia compartida y loguear la información
                if purchase.terapia and purchase.terapia.tipo in ['pareja', 'familiar']:
                    miembros = MiembroTerapia.objects.filter(terapia=purchase.terapia)
                    logger.info(f"Compra asociada a terapia compartida {purchase.terapia.id} con {miembros.count()} miembros. Todos pueden usar las {purchase.remaining_sessions} sesiones.")

                logger.info(f"Compra (ID: {purchase.id}, Ref: {purchase.reference_code}) creada para {user.email}. Precio final: {purchase.final_price}, Estado: {purchase.payment_status}")
                response_serializer = InitiatePurchaseResponseSerializer(purchase)
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            except serializers.ValidationError as e:
                logger.warning(f"Error de validación: {e.detail}")
                return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"Error inesperado: {e}", exc_info=True)
                return Response({'error': 'Error al iniciar la compra.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            logger.warning(f"Error de validación: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
# Vista para listar las compras del usuario (usar el ReadSerializer)
class UserPurchasesView(APIView):
    permission_classes = [IsAuthenticated] 
    def get(self, request):
        user = request.user
       # if not user.is_authenticated:
          #  return Response({"error": "Usuario no autenticado"}, status=status.HTTP_401_UNAUTHORIZED)

        # Compras personales (sin terapia o con terapia individual del usuario)
        personal_purchases = Purchase.objects.filter(
            Q(user=user) & 
            (Q(terapia__isnull=True) | Q(terapia__tipo='individual', terapia__miembroterapia__usuario=user))
        )

        # Compras compartidas (terapias de pareja o familiar donde el usuario es miembro)
        shared_therapy_ids = MiembroTerapia.objects.filter(
            usuario=user,
            terapia__tipo__in=['pareja', 'familiar'] # Solo terapias compartidas
        ).values_list('terapia_id', flat=True)

        # Construir la consulta final filtrando por usuario o terapia compartida
        # Y AÑADIENDO EL FILTRO DE payment_status='completed'
        purchases_query = Purchase.objects.filter(
            # Condición 1: La compra es del usuario Y (es genérica O es de su terapia individual)
            (Q(user=user) & (Q(terapia__isnull=True) | Q(terapia__tipo='individual', terapia__miembroterapia__usuario=user))) |
            # Condición 2: La compra pertenece a una de las terapias compartidas del usuario
            Q(terapia_id__in=shared_therapy_ids)
        ).filter(
            payment_status='completed' # <<< ¡¡¡ EL FILTRO ESENCIAL !!!
        ).distinct().order_by('-purchase_date') # Ordenar y asegurar unicidad
        # --- FIN: Consulta MODIFICADA ---


        # El serializer es el mismo, ahora solo recibe compras completadas
        serializer = PurchaseReadSerializer(purchases_query, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
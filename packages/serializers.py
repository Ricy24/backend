from rest_framework import serializers
from .models import Purchase, SessionPricingTier, Terapia, DiscountCode  # Asegúrate de importar DiscountCode
from django.conf import settings
from django.utils import timezone
import decimal
import uuid
from api.models import MiembroTerapia
import logging 

logger = logging.getLogger(__name__) 
class SessionPricingTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionPricingTier
        fields = ['id', 'therapy_type', 'min_sessions', 'max_sessions', 'price_per_session', 'is_active']

base_fields = [
    'id', 'user', 'terapia', 'therapy_type_purchased', 'purchased_session_count',
    'price_per_session_applied', 'base_price', 'discount_code', 'discount_applied_amount',
    'final_price', 'purchase_date', 'payment_status', 'get_payment_status_display',
    'remaining_sessions', 'reference_code', 'transaction_id', 'payment_provider', 'error_message'
]

# packages/serializers.py
class PurchaseReadSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()
    terapia = serializers.StringRelatedField(read_only=True)
    discount_code = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Purchase
        fields = [
            'id', 'user', 'terapia', 'therapy_type_purchased', 'purchased_session_count',
            'price_per_session_applied', 'base_price', 'discount_code', 'discount_applied_amount',
            'final_price', 'purchase_date', 'payment_status', 'remaining_sessions',
            'reference_code', 'transaction_id', 'payment_provider', 'error_message'
        ]
        read_only_fields = fields

class PurchaseCreateSerializer(serializers.ModelSerializer):
    therapy_type = serializers.CharField(write_only=True)
    session_count = serializers.IntegerField(write_only=True)
    discount_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    # terapia_id sigue siendo opcional desde el frontend
    terapia_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Purchase
        fields = ['therapy_type', 'session_count', 'terapia_id', 'discount_code']

    def validate(self, data):
        therapy_type = data['therapy_type'].lower()
        session_count = data.get('session_count')
        # Obtener discount_code y terapia_id como vienen, podrían ser None
        discount_code_str = data.get('discount_code')
        terapia_id_input = data.get('terapia_id') # El ID que PUDO venir del input
        user = self.context['request'].user
        final_terapia_id = None # Variable para almacenar el ID de terapia final a guardar

        # --- Validación básica de tipo y cuenta ---
        if not therapy_type:
            raise serializers.ValidationError("Se requiere 'therapy_type'.")
        if session_count is None:
            raise serializers.ValidationError("Se requiere 'session_count'.")
        try:
            session_count = int(session_count)
            if session_count <= 0:
                raise ValueError("El número de sesiones debe ser positivo.")
        except (ValueError, TypeError):
            raise serializers.ValidationError("'session_count' debe ser un entero positivo.")
        # --- Fin Validación básica ---

        # --- Lógica de Asociación de Terapia ---
        terapia = None # Objeto Terapia (si se encuentra/asocia)

        if therapy_type in ['pareja', 'familiar']:
            if not terapia_id_input:
                raise serializers.ValidationError(f"Las compras de tipo '{therapy_type}' requieren seleccionar una terapia específica.")
            try:
                terapia = Terapia.objects.get(id=terapia_id_input)
                if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                    raise serializers.ValidationError("No eres miembro de la terapia especificada.")
                if therapy_type != terapia.tipo:
                    raise serializers.ValidationError(f"El tipo comprado ({therapy_type}) no coincide con el tipo de la terapia seleccionada ({terapia.tipo}).")
                final_terapia_id = terapia.id # Se usa el ID proporcionado
            except Terapia.DoesNotExist:
                raise serializers.ValidationError("La terapia especificada no existe.")

        elif therapy_type == 'individual':
            if terapia_id_input:
                # Si el usuario explícitamente seleccionó una terapia individual (menos común ahora)
                try:
                    terapia = Terapia.objects.get(id=terapia_id_input)
                    if terapia.tipo != 'individual':
                         raise serializers.ValidationError("Solo se pueden asociar compras individuales a terapias individuales.")
                    if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                         raise serializers.ValidationError("No eres miembro de la terapia individual especificada.")
                    final_terapia_id = terapia.id # Usa el ID proporcionado
                    logger.info(f"Compra individual asociada explícitamente a Terapia ID {final_terapia_id} por {user.email}")
                except Terapia.DoesNotExist:
                    raise serializers.ValidationError("La terapia individual especificada no existe.")
            else:
                # *** INICIO: Lógica de Auto-Asociación para Individual ***
                # Busca si el usuario tiene EXACTAMENTE UNA terapia individual activa
                user_individual_therapies = Terapia.objects.filter(
                    miembroterapia__usuario=user,
                    tipo='individual',
                    # Podrías añadir filtros de activa=True si tienes ese campo en Terapia
                ).distinct() # distinct por si hay duplicados en MiembroTerapia (aunque no debería)

                if user_individual_therapies.count() == 1:
                    terapia = user_individual_therapies.first()
                    final_terapia_id = terapia.id
                    logger.info(f"Compra individual auto-asociada a Terapia ID {final_terapia_id} para {user.email}")
                else:
                    # Si tiene 0 o más de 1, la compra se queda genérica
                    final_terapia_id = None
                    logger.info(f"Compra individual permanece genérica para {user.email} (encontradas {user_individual_therapies.count()} terapias individuales).")
                # *** FIN: Lógica de Auto-Asociación ***
        else:
             raise serializers.ValidationError(f"Tipo de terapia '{therapy_type}' no reconocido.")
        # --- Fin Lógica de Asociación de Terapia ---


        # --- Validación de Código de Descuento ---
        discount_code_obj = None
        if discount_code_str:
            try:
                # Validación más robusta del código (activo, no expirado, usos restantes, aplicable al tipo?)
                discount_code_obj = DiscountCode.objects.get(
                    code=discount_code_str,
                    is_active=True,
                    valid_from__lte=timezone.now(),
                    valid_to__gte=timezone.now(),
                    # Opcional: Verificar usos restantes si tienes ese campo
                    # max_uses__gt=F('times_used') # Necesitarías importar F de django.db.models
                    # Opcional: Verificar si aplica a este tipo de terapia
                    # Q(applies_to_therapy_type__isnull=True) | Q(applies_to_therapy_type=therapy_type)
                )
                # Opcional: Verificar si el usuario ya usó este código si es de un solo uso por usuario
                # if discount_code_obj.one_time_per_user and Purchase.objects.filter(user=user, discount_code=discount_code_obj).exists():
                #     raise serializers.ValidationError("Ya has utilizado este código de descuento.")

            except DiscountCode.DoesNotExist:
                 # Ser más específico en el error
                raise serializers.ValidationError(f"El código de descuento '{discount_code_str}' no es válido, ha expirado o no aplica.")
        # --- Fin Validación Descuento ---


        # --- Cálculo y Validación de Precio Final ---
        try:
            # Pasar el objeto DiscountCode si se encontró, o el string si no (calculate_price debería manejar None)
            price_data = Purchase.calculate_price(therapy_type, session_count, discount_code_obj) # Pasar objeto o None
            final_price = price_data['final_price']

            # Asegurar que es Decimal y positivo
            if not isinstance(final_price, decimal.Decimal):
                try:
                    final_price = decimal.Decimal(str(final_price))
                except decimal.InvalidOperation:
                     raise serializers.ValidationError("Error interno al calcular el precio final.")
            if final_price < 0: # Permitir precio 0 si el descuento cubre todo? O requerir > 0?
                 # Ajusta esta lógica si permites sesiones 100% gratuitas con cupón
                 raise serializers.ValidationError(f"El precio final ({final_price}) no puede ser negativo.")
            # Decisión: ¿Permitir compras de $0? Si no, descomenta:
            # if final_price <= 0:
            #      raise serializers.ValidationError("El precio final debe ser mayor a cero.")

        except ValueError as e: # Errores desde calculate_price (ej. no hay tier)
            raise serializers.ValidationError(str(e))
        except Exception as e: # Otros errores inesperados
             logger.error(f"Error inesperado calculando precio: {e}", exc_info=True)
             raise serializers.ValidationError("Error interno al calcular el precio.")
        # --- Fin Cálculo Precio ---


        # --- Preparar Datos Validados Finales ---
        validated_data = {
            'user': user,
            'terapia_id': final_terapia_id, # Usar el ID final determinado
            'therapy_type_purchased': therapy_type,
            'purchased_session_count': session_count,
            'price_per_session_applied': price_data['price_per_session'],
            'base_price': price_data['base_price'],
            'discount_code': price_data['discount_code'], # Usar el objeto que devolvió calculate_price
            'discount_applied_amount': price_data['discount_amount'],
            'final_price': final_price,
            'remaining_sessions': session_count, # Asignar sesiones iniciales
             # Campos que se asignarán en create o por defecto en el modelo:
             # 'payment_status', 'reference_code', 'transaction_id', 'payment_provider', 'error_message', 'purchase_date'
        }
        return validated_data

    def create(self, validated_data):
        # ... (La lógica de create no necesita cambiar significativamente) ...
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        unique_id = uuid.uuid4().hex[:6]
        reference_code = f"REF-{timestamp}-{unique_id}"

        # Crear la instancia de Purchase usando los datos validados
        # Asegúrate que el modelo Purchase tenga valores por defecto adecuados
        # para campos como payment_status (ej. 'pending')
        purchase = Purchase.objects.create(
            user=validated_data['user'],
            # Usar terapia_id del diccionario validado (puede ser None)
            terapia_id=validated_data.get('terapia_id'),
            therapy_type_purchased=validated_data['therapy_type_purchased'],
            purchased_session_count=validated_data['purchased_session_count'],
            price_per_session_applied=validated_data['price_per_session_applied'],
            base_price=validated_data['base_price'],
            # Usar el objeto discount_code del diccionario validado (puede ser None)
            discount_code=validated_data.get('discount_code'),
            discount_applied_amount=validated_data['discount_applied_amount'],
            final_price=validated_data['final_price'],
            reference_code=reference_code,
            # remaining_sessions se asigna desde validated_data
            remaining_sessions=validated_data['remaining_sessions']
            # payment_status debería tener un default='pending' en el modelo
        )
        # Loguear la compra creada con el ID de terapia final
        logger.info(f"Purchase creada ID: {purchase.id}, Ref: {purchase.reference_code}, Terapia asociada ID: {purchase.terapia_id}")
        return purchase


class InitiatePurchaseResponseSerializer(serializers.ModelSerializer):
    purchase_id = serializers.IntegerField(source='id')
    discount_applied = serializers.DecimalField(max_digits=10, decimal_places=2, source='discount_applied_amount')
    discount_code_used = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = ['purchase_id', 'reference_code', 'final_price', 'message', 'base_price', 'discount_applied', 'discount_code_used']

    def get_message(self, obj):
        return 'Compra iniciada. Procede al pago.'

    def get_discount_code_used(self, obj):
        return obj.discount_code.code if obj.discount_code else None
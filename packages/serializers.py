from rest_framework import serializers
from .models import Purchase, SessionPricingTier, Terapia, DiscountCode
from django.conf import settings
from django.utils import timezone
import decimal
import uuid
from api.models import MiembroTerapia
import logging
from django.db.models import Q # <<<--- IMPORTANTE: Añadir esta importación


logger = logging.getLogger(__name__)

class SessionPricingTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionPricingTier
        fields = ['id', 'therapy_type', 'min_sessions', 'max_sessions', 'price_per_session', 'is_active']

# No estoy seguro si 'base_fields' se usa en alguna parte, pero lo dejo como estaba.
base_fields = [
    'id', 'user', 'terapia', 'therapy_type_purchased', 'purchased_session_count',
    'price_per_session_applied', 'base_price', 'discount_code', 'discount_applied_amount',
    'final_price', 'purchase_date', 'payment_status', 'get_payment_status_display',
    'remaining_sessions', 'reference_code', 'transaction_id', 'payment_provider', 'error_message'
]

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
    terapia_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Purchase
        fields = ['therapy_type', 'session_count', 'terapia_id', 'discount_code']

    def validate(self, data):
        therapy_type = data['therapy_type'].lower()
        session_count = data.get('session_count')
        discount_code_str = data.get('discount_code')
        terapia_id_input = data.get('terapia_id')
        user = self.context['request'].user
        final_terapia_id = None

        # --- Validación básica de tipo y cuenta ---
        if not therapy_type:
            raise serializers.ValidationError({"therapy_type": "Se requiere 'therapy_type'."})
        if session_count is None:
            raise serializers.ValidationError({"session_count": "Se requiere 'session_count'."})
        try:
            session_count = int(session_count)
            if session_count <= 0:
                # Corregido para que lance ValidationError directamente
                raise serializers.ValidationError({"session_count": "El número de sesiones debe ser positivo."})
        except (ValueError, TypeError):
            raise serializers.ValidationError({"session_count": "'session_count' debe ser un entero positivo."})
        # --- Fin Validación básica ---

        # --- Lógica de Asociación de Terapia ---
        terapia = None # Objeto Terapia (si se encuentra/asocia)

        if therapy_type in ['pareja', 'familiar']:
            if not terapia_id_input:
                raise serializers.ValidationError({"terapia_id": f"Las compras de tipo '{therapy_type}' requieren seleccionar una terapia específica."})
            try:
                terapia = Terapia.objects.get(id=terapia_id_input)
                if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                    raise serializers.ValidationError({"terapia_id": "No eres miembro de la terapia especificada."})
                if therapy_type != terapia.tipo:
                    raise serializers.ValidationError({"terapia_id": f"El tipo comprado ({therapy_type}) no coincide con el tipo de la terapia seleccionada ({terapia.tipo})."})
                final_terapia_id = terapia.id
            except Terapia.DoesNotExist:
                raise serializers.ValidationError({"terapia_id": "La terapia especificada no existe."})

        elif therapy_type == 'individual':
            if terapia_id_input:
                try:
                    terapia = Terapia.objects.get(id=terapia_id_input)
                    if terapia.tipo != 'individual':
                         raise serializers.ValidationError({"terapia_id": "Solo se pueden asociar compras individuales a terapias individuales."})
                    if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                         raise serializers.ValidationError({"terapia_id": "No eres miembro de la terapia individual especificada."})
                    final_terapia_id = terapia.id
                    logger.info(f"Compra individual asociada explícitamente a Terapia ID {final_terapia_id} por {user.email}")
                except Terapia.DoesNotExist:
                    raise serializers.ValidationError({"terapia_id": "La terapia individual especificada no existe."})
            else:
                user_individual_therapies = Terapia.objects.filter(
                    miembroterapia__usuario=user,
                    tipo='individual',
                ).distinct()

                if user_individual_therapies.count() == 1:
                    terapia = user_individual_therapies.first()
                    final_terapia_id = terapia.id
                    logger.info(f"Compra individual auto-asociada a Terapia ID {final_terapia_id} para {user.email}")
                else:
                    final_terapia_id = None
                    logger.info(f"Compra individual permanece genérica para {user.email} (encontradas {user_individual_therapies.count()} terapias individuales).")
        else:
             raise serializers.ValidationError({"therapy_type": f"Tipo de terapia '{therapy_type}' no reconocido."})
        # --- Fin Lógica de Asociación de Terapia ---


        # --- Validación de Código de Descuento ---
        # Definir discount_code_obj_for_purchase para guardar en el modelo Purchase
        # y discount_code_for_price_calc para pasar al método calculate_price
        discount_code_obj_for_purchase = None
        discount_code_for_price_calc = None

        if discount_code_str: # Solo si se proporcionó un código
            try:
                # Intenta obtener el código.
                # Condiciones: código existe, está activo, Y (no ha expirado SI tiene fecha de expiración O no tiene fecha de expiración)
                temp_discount_code = DiscountCode.objects.filter(
                    code=discount_code_str,
                    is_active=True
                ).filter(
                    Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.now())
                ).get()

                # Ahora que tenemos un candidato, usamos el método is_valid() del modelo
                # Este método ya maneja la lógica de 'is_active', 'valid_until' y 'max_uses'.
                is_code_ok, error_msg = temp_discount_code.is_valid()
                if is_code_ok:
                    discount_code_obj_for_purchase = temp_discount_code # Este es el objeto que guardaremos
                    discount_code_for_price_calc = temp_discount_code # Y el que pasamos a calculate_price
                else:
                    # El método is_valid() del modelo ya nos da un mensaje de error apropiado
                    raise serializers.ValidationError({"discount_code": error_msg})

            except DiscountCode.DoesNotExist:
                # Si DiscountCode.objects.get falla (no encuentra el código con las condiciones iniciales)
                raise serializers.ValidationError({"discount_code": f"El código de descuento '{discount_code_str}' no es válido, ha expirado o no se encontró."})
        # --- Fin Validación Descuento ---


        # --- Cálculo y Validación de Precio Final ---
        try:
            # Pasar el objeto DiscountCode (discount_code_for_price_calc) si se encontró y validó, o None.
            price_data = Purchase.calculate_price(therapy_type, session_count, discount_code_for_price_calc)
            final_price = price_data['final_price']

            # Si el método calculate_price detectó un error con el descuento que no se capturó antes
            if price_data.get("discount_error"):
                raise serializers.ValidationError({"discount_code": price_data["discount_error"]})

            if not isinstance(final_price, decimal.Decimal):
                try:
                    final_price = decimal.Decimal(str(final_price))
                except decimal.InvalidOperation:
                     raise serializers.ValidationError("Error interno al calcular el precio final.") # Error genérico para el usuario
            if final_price < 0:
                 raise serializers.ValidationError(f"El precio final ({final_price}) no puede ser negativo.")
            # if final_price <= 0: # Descomenta si no permites compras de $0
            #      raise serializers.ValidationError("El precio final debe ser mayor a cero.")

        except ValueError as e: # Errores desde calculate_price (ej. no hay tier) o validaciones previas
            # Si el error es una instancia de serializers.ValidationError, relanzarlo.
            if isinstance(e, serializers.ValidationError):
                raise e
            # Para otros ValueErrors, envolverlos.
            raise serializers.ValidationError(str(e))
        except Exception as e: # Otros errores inesperados
             logger.error(f"Error inesperado calculando precio: {e}", exc_info=True)
             raise serializers.ValidationError("Error interno al calcular el precio.") # Error genérico
        # --- Fin Cálculo Precio ---


        # --- Preparar Datos Validados Finales ---
        # Aquí se almacenan los datos que se usarán para crear la instancia de Purchase
        validated_data = {
            'user': user,
            'terapia_id': final_terapia_id,
            'therapy_type_purchased': therapy_type,
            'purchased_session_count': session_count,
            'price_per_session_applied': price_data['price_per_session'],
            'base_price': price_data['base_price'],
            'discount_code': discount_code_obj_for_purchase, # Guardar el objeto DiscountCode validado
            'discount_applied_amount': price_data['discount_amount'],
            'final_price': final_price,
            'remaining_sessions': session_count,
        }
        return validated_data

    def create(self, validated_data):
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        unique_id = uuid.uuid4().hex[:6]
        reference_code = f"REF-{timestamp}-{unique_id}"

        # 'validated_data' ya contiene 'discount_code' como un objeto DiscountCode o None
        purchase = Purchase.objects.create(
            user=validated_data['user'],
            terapia_id=validated_data.get('terapia_id'), # Puede ser None
            therapy_type_purchased=validated_data['therapy_type_purchased'],
            purchased_session_count=validated_data['purchased_session_count'],
            price_per_session_applied=validated_data['price_per_session_applied'],
            base_price=validated_data['base_price'],
            discount_code=validated_data.get('discount_code'), # Objeto DiscountCode o None
            discount_applied_amount=validated_data['discount_applied_amount'],
            final_price=validated_data['final_price'],
            reference_code=reference_code,
            remaining_sessions=validated_data['remaining_sessions']
            # payment_status debería tener un default='pending' en el modelo
        )
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
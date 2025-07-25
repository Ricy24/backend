# api/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError # Renombrar para evitar conflicto
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.utils import timezone # Importar timezone para RegisterSerializer
from django.db import transaction # Import transaction
from .models import Usuario, Terapia, MiembroTerapia
from psychologist.serializers import SpecialtySerializer, LanguageSerializer# Para leer/validar
from psychologist.models import Specialty, Language
from psychologist.models import PsychologistProfile # Asegúrate de importar tu modelo de perfil



User = get_user_model() # Obtiene tu modelo Usuario personalizado

# --- Serializer para Registro de Usuarios Normales ---
class RegisterSerializer(serializers.ModelSerializer):
    gender = serializers.ChoiceField(choices=Usuario.GENDER_CHOICES, required=True)
    # Considera añadir validación de contraseña si no usas django_validate_password
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = [
            'email', 'password', 'nombre', 'telefono', 'birthdate', 'country',
            'gender'
        ]
        extra_kwargs = {
            'password': {'write_only': True},
            # Puedes añadir más aquí si es necesario
             'nombre': {'required': False, 'allow_blank': True}, # Hacer opcional si se permite
             'telefono': {'required': False, 'allow_blank': True},
             'birthdate': {'required': False, 'allow_null': True},
             'country': {'required': False, 'allow_blank': True},
        }

    def validate_email(self, value):
        # Convertir a minúsculas antes de verificar y guardar
        email_lower = value.lower()
        if User.objects.filter(email=email_lower).exists():
            raise serializers.ValidationError("El email ya está registrado.")
        return email_lower

    def validate_birthdate(self, value):
        # Permite que birthdate sea None si es opcional
        if value is None:
            return None
        today = timezone.now().date()
        # Ajusta la edad mínima si es necesario
        min_birthdate = today.replace(year=today.year - 16)
        if value > min_birthdate:
            raise serializers.ValidationError("Debes tener al menos 16 años.")
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'], # Ya está en minúsculas por validate_email
            password=validated_data['password'],
            nombre=validated_data.get('nombre'), # get maneja None/ausencia
            telefono=validated_data.get('telefono'),
            birthdate=validated_data.get('birthdate'),
            country=validated_data.get('country'),
            gender=validated_data.get('gender'),
            is_psychologist=False, # Importante: Falso para registro normal
            is_new_user=True
            # Otros campos por defecto si los tienes
        )
        return user

# --- Serializer para Registro de Psicólogas ---
class PsychologistRegisterSerializer(serializers.ModelSerializer):
    # --- Campos de Usuario ---
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    nombre = serializers.CharField(required=True, max_length=255)
    email = serializers.EmailField(required=True)
    profile_pic = serializers.ImageField(required=True, allow_empty_file=False) # Hacer requerido

    # --- Campos de PsychologistProfile ---
    # Usamos PrimaryKeyRelatedField para recibir IDs de especialidades/idiomas del frontend
    # El frontend deberá enviar una lista de IDs [1, 3, 5]
    specialties = serializers.PrimaryKeyRelatedField(
        queryset=Specialty.objects.all(),
        many=True,
        required=False # Hacer opcional si pueden registrarse sin especialidades iniciales
    )
    languages = serializers.PrimaryKeyRelatedField(
        queryset=Language.objects.all(),
        many=True,
        required=False # Hacer opcional si pueden registrarse sin idiomas iniciales
    )
    bio = serializers.CharField(max_length=500, required=False, allow_blank=True)
    years_experience = serializers.IntegerField(min_value=0, max_value=70, required=False, default=0)
    therapeutic_approach = serializers.CharField(max_length=100, required=False, allow_blank=True)
    offers_free_30min_session = serializers.BooleanField(required=False, default=False)
    # Añade 'gender', 'birthdate', 'country', 'telefono' si también los quieres en este registro
    gender = serializers.ChoiceField(choices=Usuario.GENDER_CHOICES, required=False)
    birthdate = serializers.DateField(required=False, allow_null=True)
    country = serializers.CharField(max_length=2, required=False, allow_blank=True)
    telefono = serializers.CharField(max_length=20, required=False, allow_blank=True)


    class Meta:
        model = User
        # Incluir todos los campos que se recibirán en el JSON/FormData
        fields = [
            'email', 'nombre', 'password', 'profile_pic', 'bio', 'specialties',
            'languages', 'years_experience', 'therapeutic_approach',
            'offers_free_30min_session', 'gender', 'birthdate', 'country', 'telefono'
        ]
        # No necesitas extra_kwargs si defines los campos explícitamente arriba

    def validate_email(self, value):
        email_lower = value.lower()
        if User.objects.filter(email=email_lower).exists():
            raise serializers.ValidationError("Este correo electrónico ya está registrado.")
        return email_lower

    def validate_password(self, value):
        try:
            django_validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate_birthdate(self, value):
         if value is None:
             return None
         today = timezone.now().date()
         min_birthdate = today.replace(year=today.year - 18) # Quizás 18 para psicólogos? O 16?
         if value > min_birthdate:
             raise serializers.ValidationError("Debes tener al menos 18 años.")
         return value

    def validate_profile_pic(self, value):
        # Añadir validaciones de tamaño/tipo si es necesario
        if value.size > 5 * 1024 * 1024: # Límite de 5MB
             raise serializers.ValidationError("La imagen es demasiado grande (máx 5MB).")
        # Puedes añadir validación de tipo de archivo aquí también
        return value

    @transaction.atomic # Envuelve la creación en una transacción
    def create(self, validated_data):
        # Separar datos de Usuario y Perfil
        profile_pic_data = validated_data.pop('profile_pic')
        specialties_data = validated_data.pop('specialties', [])
        languages_data = validated_data.pop('languages', [])
        bio_data = validated_data.pop('bio', '')
        years_experience_data = validated_data.pop('years_experience', 0)
        therapeutic_approach_data = validated_data.pop('therapeutic_approach', '')
        offers_free_data = validated_data.pop('offers_free_30min_session', False)
        # Datos opcionales de Usuario
        gender_data = validated_data.pop('gender', None)
        birthdate_data = validated_data.pop('birthdate', None)
        country_data = validated_data.pop('country', None)
        telefono_data = validated_data.pop('telefono', None)


        # Crear Usuario Básico
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            nombre=validated_data['nombre'],
            gender=gender_data,
            birthdate=birthdate_data,
            country=country_data,
            telefono=telefono_data,
            is_psychologist=True,
            is_active=True, # O False si necesita verificación
            is_new_user=True
        )

        # Asignar y guardar la foto de perfil DESPUÉS de crear el usuario
        user.profile_pic = profile_pic_data
        user.save(update_fields=['profile_pic']) # Guardar solo el campo de la foto

        # Crear Perfil de Psicólogo
        profile = PsychologistProfile.objects.create(
            user=user,
            bio=bio_data,
            years_experience=years_experience_data,
            therapeutic_approach=therapeutic_approach_data,
            offers_free_30min_session=offers_free_data
        )

        # Asignar relaciones ManyToMany
        if specialties_data:
            profile.specialties.set(specialties_data)
        if languages_data:
            profile.languages.set(languages_data)

        return user # Devuelve la instancia del Usuario creado

# --- Serializer para mostrar/actualizar datos del Usuario ---
class UserSerializer(serializers.ModelSerializer):
    dias_activos = serializers.ReadOnlyField()
    public_likes = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'nombre',
            'telefono',
            'birthdate',
            'country',
            'gender',
            'fecha_registro',
            'ultima_sesion',
            'tipo_cuenta',
            'sesiones_completadas',
            'email_notifications',
            'push_notifications',
            'is_psychologist',
            'is_new_user',
            'dias_activos',
            'public_likes',
            'profile_pic', # <--- ¡¡¡ AÑADIDO !!!
        ]
        read_only_fields = [
            'id', 'email', 'fecha_registro', 'ultima_sesion', 'tipo_cuenta',
            'sesiones_completadas', 'is_psychologist', 'dias_activos'
            # No necesitas poner 'profile_pic' aquí si permites que se actualice
            # (lo cual haces en UpdateMyPsychologistProfileView)
        ]

    def get_public_likes(self, obj):
        # Tu lógica existente para obtener likes...
        # Asegúrate que esto funcione o ajústalo.
        profile = getattr(obj, 'psychologist_profile', None) # Es más probable que sea este related_name
        if profile:
            return getattr(profile, 'public_likes', False)
        return False


# --- Serializers relacionados con Terapia ---
class SimpleMiembroSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='usuario.id')
    nombre = serializers.CharField(source='usuario.nombre', allow_null=True)

    class Meta:
        model = MiembroTerapia
        fields = ['id', 'nombre']


class TerapiaSerializer(serializers.ModelSerializer):
    # Mostrar información del miembro (solo habrá uno en terapia individual)
    miembro = SimpleMiembroSerializer(source='miembroterapia_set.first', read_only=True)

    class Meta:
        model = Terapia
        fields = ['id', 'tipo', 'herramientas', 'fecha_creacion', 'miembro']
        read_only_fields = ['fecha_creacion']


class MiembroTerapiaSerializer(serializers.ModelSerializer):
    # Usar source para acceder a campos del modelo relacionado 'usuario'
    usuario_email = serializers.EmailField(source='usuario.email', read_only=True)
    usuario_nombre = serializers.CharField(source='usuario.nombre', read_only=True, allow_null=True)
    usuario_id = serializers.IntegerField(source='usuario.id', read_only=True)

    class Meta:
        model = MiembroTerapia
        fields = ['usuario_id', 'usuario_email', 'usuario_nombre', 'fecha_union']
        read_only_fields = ['fecha_union']
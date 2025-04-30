# psychologist/serializers.py
from rest_framework import serializers
from api.models import Usuario
from .models import Availability, PsychologistProfile, Specialty, Language, Certification

class SpecialtySerializer(serializers.ModelSerializer):
    class Meta:
        model = Specialty
        fields = ['name']

class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = ['name']

class CertificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Certification
        fields = ['name']

class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Availability
        fields = ['id', 'day_of_week', 'start_time', 'end_time', 'created_at', 'updated_at']

class PsychologistProfileSerializer(serializers.ModelSerializer):
    specialties = SpecialtySerializer(many=True, read_only=True)
    languages = LanguageSerializer(many=True, read_only=True)
    certifications = CertificationSerializer(many=True, read_only=True)

    class Meta:
        model = PsychologistProfile
        fields = [
            'specialties',
            'bio',
            'languages',
            'years_experience',
            'therapeutic_approach',
            'certifications',
            'offers_free_30min_session',
            'created_at',
            'updated_at'
        ]

class PsychologistSerializer(serializers.ModelSerializer):
    availability = AvailabilitySerializer(many=True, read_only=True) # <- SIN SOURCE
    profile = PsychologistProfileSerializer(read_only=True, source='psychologist_profile') # Mantenemos source aquí porque el campo se llama 'profile' pero el atributo en Usuario es 'psychologist_profile'

    class Meta:
        model = Usuario
        fields = [
            'id',
            'nombre',
            'email',
            'profile_pic',
            'gender',
            'country',
            'availability', # El nombre del campo coincide con el related_name
            'profile'
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation['profile_pic'] = instance.profile_pic.url if instance.profile_pic else None
        # Esta verificación es buena, la mantenemos
        if not hasattr(instance, 'psychologist_profile'):
             representation['profile'] = None
        # Podrías añadir una verificación similar para availability si fuera necesario,
        # aunque prefetch_related debería manejarlo.
        # if not hasattr(instance, 'availability'):
        #      representation['availability'] = []
        return representation
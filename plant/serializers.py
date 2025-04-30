# plant/serializers.py
from rest_framework import serializers
# --- SOLO IMPORTAR Plant ---
from .models import Plant
# from .models import Plant, CareAction <-- Eliminar CareAction de aquí

class PlantSerializer(serializers.ModelSerializer):
    # Puedes añadir campos calculados o relacionados si es necesario
    # therapy_type = serializers.CharField(source='terapia.tipo', read_only=True)

    class Meta:
        model = Plant
        # Añadir 'is_alive' a los campos devueltos si quieres que el frontend lo sepa
        fields = [
            'id', 'terapia', 'name', 'type', 'design', 'level',
            'current_streak', 'last_care_date', 'is_alive', # <-- Añadido is_alive
            'created_at', 'updated_at'
        ]
        # Hacer campos calculados read-only
        read_only_fields = ('level', 'current_streak', 'last_care_date', 'is_alive', 'created_at', 'updated_at')


# --- ELIMINAR O COMENTAR TODO ESTE SERIALIZER ---
# class CareActionSerializer(serializers.ModelSerializer):
#     # Podrías añadir el email del usuario si quieres
#     # user_email = serializers.EmailField(source='user.email', read_only=True)
#     class Meta:
#         model = CareAction
#         fields = ['id', 'plant', 'user', 'action_date', 'action_type']
# --- FIN DE LA ELIMINACIÓN ---
# marketplace/serializers.py

from rest_framework import serializers
from psychologist.models import PsychologistProfile, Specialty, Language
from api.models import Usuario
from .models import Education, Recommendation, BlogPost

# --- Serializers para los modelos anidados ---
# Estos ya están bien, no los toques
class EducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Education
        fields = ['id', 'institution', 'degree', 'field_of_study', 'start_year', 'end_year']

class RecommendationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recommendation
        fields = ['id', 'title', 'type', 'link', 'description', 'cover_image']

class BlogPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogPost
        fields = ['id', 'title', 'content', 'header_image', 'published_at', 'updated_at']


# ==========================================================
# >>> PASO 1: Crea un serializer para el usuario <<<
# Este es el cambio más importante.
# ==========================================================
class UserNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        # El ImageField aquí sí tendrá el contexto para construir la URL
        fields = ['id', 'nombre', 'email', 'profile_pic']


# ==========================================================
# >>> PASO 2: Modifica tus serializers de Psicólogo <<<
# Usa el nuevo UserNestedSerializer en lugar de `source`.
# ==========================================================

# --- Serializer para la lista pública de psicólogos (vista de "tarjetas") ---
class PsychologistListSerializer(serializers.ModelSerializer):
    # En lugar de usar 'source', anidamos el serializer de usuario
    user = UserNestedSerializer(read_only=True)
    
    # Obtenemos campos de ManyToMany (esto está bien)
    specialties = serializers.StringRelatedField(many=True)

    class Meta:
        model = PsychologistProfile
        fields = [
            'id',  # Es mejor usar el ID del perfil, no el del usuario
            'user', # Esto ahora devolverá un objeto con nombre, email, y profile_pic completo
            'bio',
            'specialties',
        ]

# --- Serializer para el perfil detallado público ---
class PsychologistDetailSerializer(serializers.ModelSerializer):
    # Reutilizamos el mismo patrón
    user = UserNestedSerializer(read_only=True)
    
    # Campos de ManyToMany con más detalle (esto está bien)
    specialties = serializers.StringRelatedField(many=True)
    languages = serializers.StringRelatedField(many=True)

    # Serializers anidados para obtener toda la información relacionada (esto está bien)
    education = EducationSerializer(many=True, read_only=True)
    recommendations = RecommendationSerializer(many=True, read_only=True)
    blog_posts = BlogPostSerializer(many=True, read_only=True)

    class Meta:
        model = PsychologistProfile
        fields = [
            'id', # De nuevo, usa el ID del perfil
            'user',
            'bio',
            # 'license_number', # Descomenta si este campo existe en tu modelo
            'years_experience',
            'specialties',
            'languages',
            'education',
            'recommendations',
            'blog_posts',
        ]
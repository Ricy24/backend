# marketplace/views.py

from rest_framework import viewsets, permissions
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from psychologist.models import PsychologistProfile
from .models import Education, Recommendation, BlogPost
from .serializers import (
    PsychologistListSerializer, 
    PsychologistDetailSerializer,
    EducationSerializer,
    RecommendationSerializer,
    BlogPostSerializer
)

# --- Vistas Públicas (cualquiera puede verlas) ---

class PsychologistPublicViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint público para listar y ver perfiles de psicólogos.
    - `list`: Muestra una lista de tarjetas de psicólogos.
    - `retrieve`: Muestra el perfil detallado de un psicólogo.
    Soporta filtros y búsqueda.
    """
    # Filtramos solo los perfiles que el psicólogo ha marcado como visibles
    queryset = PsychologistProfile.objects.filter(profile_visibility=True, user__is_psychologist=True)
    permission_classes = [permissions.AllowAny] # Abierto al público
    
    # Filtros para la URL (ej. /api/marketplace/psychologists/?specialties__name=Ansiedad)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['specialties__name', 'languages__name']
    search_fields = ['user__nombre', 'bio', 'specialties__name'] # Búsqueda de texto libre
    ordering_fields = ['years_of_experience']

    def get_serializer_class(self):
        # Usamos un serializer para la lista y otro para el detalle
        if self.action == 'list':
            return PsychologistListSerializer
        return PsychologistDetailSerializer


# --- Vistas Privadas (solo para el psicólogo autenticado) ---

class IsPsychologistOwner(permissions.BasePermission):
    """Permiso para asegurar que solo el dueño del perfil puede editarlo."""
    def has_object_permission(self, request, view, obj):
        # obj es la instancia del modelo (Education, Recommendation, etc.)
        return obj.psychologist_profile.user == request.user

class MyEducationViewSet(viewsets.ModelViewSet):
    """Maneja el CRUD para la formación del psicólogo logueado."""
    serializer_class = EducationSerializer
    permission_classes = [permissions.IsAuthenticated, IsPsychologistOwner]
    
    def get_queryset(self):
        return Education.objects.filter(psychologist_profile__user=self.request.user)

    def perform_create(self, serializer):
        # Asocia automáticamente el nuevo registro con el perfil del psicólogo logueado
        profile = PsychologistProfile.objects.get(user=self.request.user)
        serializer.save(psychologist_profile=profile)

# Repetimos el patrón para Recomendaciones y Blog
class MyRecommendationViewSet(viewsets.ModelViewSet):
    serializer_class = RecommendationSerializer
    permission_classes = [permissions.IsAuthenticated, IsPsychologistOwner]
    
    def get_queryset(self):
        return Recommendation.objects.filter(psychologist_profile__user=self.request.user)

    def perform_create(self, serializer):
        profile = PsychologistProfile.objects.get(user=self.request.user)
        serializer.save(psychologist_profile=profile)

class MyBlogPostViewSet(viewsets.ModelViewSet):
    serializer_class = BlogPostSerializer
    permission_classes = [permissions.IsAuthenticated, IsPsychologistOwner]

    def get_queryset(self):
        return BlogPost.objects.filter(psychologist_profile__user=self.request.user)

    def perform_create(self, serializer):
        profile = PsychologistProfile.objects.get(user=self.request.user)
        serializer.save(psychologist_profile=profile)
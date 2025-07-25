# marketplace/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PsychologistPublicViewSet,
    MyEducationViewSet,
    MyRecommendationViewSet,
    MyBlogPostViewSet,
)

router = DefaultRouter()

# Rutas públicas
router.register(r'psychologists', PsychologistPublicViewSet, basename='psychologist-public')

# Rutas privadas para que el psicólogo gestione su perfil
router.register(r'my-education', MyEducationViewSet, basename='my-education')
router.register(r'my-recommendations', MyRecommendationViewSet, basename='my-recommendations')
router.register(r'my-blog-posts', MyBlogPostViewSet, basename='my-blog-posts')

urlpatterns = [
    path('', include(router.urls)),
]
# therapy/urls.py
from django.urls import path
from .views import (
    InitialScreeningAssessmentView,
    EmotionalPathView,
    UserChallengeView,
    ReplaceDailyChallengeView,
    UserPathProgressView,
    DailyComponentView,
    CollaborativeChallengeView,
)

# Opcional: Define app_name aquí si lo usas en include en el urls.py principal
# con la tupla ('therapy.urls', 'therapy')
app_name = 'therapy'

urlpatterns = [
    # Mantenemos las rutas originales, solo ajustamos los 'name'
    path('screening/assessment/', InitialScreeningAssessmentView.as_view(), name='screening-assessment'),

    # Vista: EmotionalPathView
    # Ruta: /therapy/emotional-paths/
    # Nombre que espera la prueba: activate_paths
    path('emotional-paths/', EmotionalPathView.as_view(), name='activate_paths'), # <-- CAMBIO DE 'emotional-paths' a 'activate_paths'

    # Vista: UserChallengeView
    # Ruta: /therapy/user-challenges/
    # Nombre que espera la prueba: user_challenges (¡Coincide!)
    path('user-challenges/', UserChallengeView.as_view(), name='user_challenges'), # <-- SIN CAMBIOS, YA COINCIDE

    path('daily-components/', DailyComponentView.as_view(), name='daily-components'),
    path('collaborative-challenge/', CollaborativeChallengeView.as_view(), name='collaborative-challenge'),
    path('user-progress/', UserPathProgressView.as_view(), name='user-path-progress'),

    # Vista: ReplaceDailyChallengeView
    # Ruta: /therapy/user-challenges/replace-daily/
    # Nombre que espera la prueba: replace_daily_challenge (con guion bajo)
    path('user-challenges/replace-daily/', ReplaceDailyChallengeView.as_view(), name='replace_daily_challenge'), # <-- CAMBIO de '-' a '_'
]
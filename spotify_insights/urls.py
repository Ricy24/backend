# spotify_insights/urls.py
from django.urls import path
from . import views

app_name = 'spotify_insights'

urlpatterns = [
    # Endpoint para que el frontend obtenga un 'state'
    path('get-oauth-state/', views.get_spotify_oauth_state, name='get_spotify_oauth_state'),
    
    # Endpoint al que el frontend redirige al usuario (con el 'state' como query param)
    path('redirect-to-provider/', views.spotify_redirect_to_provider, name='spotify_redirect_to_provider'),
    
    # Endpoint al que Spotify redirige de vuelta (nuestro SPOTIFY_REDIRECT_URI)
    path('callback/', views.spotify_callback_handler, name='spotify_callback_handler'),
    
    # Endpoint para que el frontend (autenticado con JWT) asocie el token temporal
    path('associate-token/', views.associate_spotify_token, name='associate_spotify_token'),
    path('generate-wrapped/', views.generate_wrapped_view, name='generate_wrapped'),
    # path('generate-wrapped/', views.generate_wrapped_view, name='generate_wrapped'), # Después
]
# spotify_insights/models.py
from django.db import models
from api.models import Usuario 
from django.utils import timezone
import secrets # Para el default state si es necesario

class SpotifyToken(models.Model):
    user = models.OneToOneField(Usuario, on_delete=models.CASCADE, null=True, blank=True) # Permitir null temporalmente
    access_token = models.CharField(max_length=300)
    refresh_token = models.CharField(max_length=300, null=True, blank=True)
    expires_in = models.DateTimeField()
    token_type = models.CharField(max_length=50, default='Bearer')
    scope = models.TextField(null=True, blank=True)
    
    # Nuevo campo para el state, debe ser único mientras esté activo
    oauth_state_key = models.CharField(max_length=50, null=True, blank=True, unique=True) # 'key' para evitar conflicto con 'state' de django models
    created_at = models.DateTimeField(auto_now_add=True) # Útil para limpiar tokens no reclamados

    def __str__(self):
        if self.user:
            return f"Token for {self.user.email}"
        return f"Unclaimed token created at {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_in
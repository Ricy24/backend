# chat/models.py
from django.conf import settings
from api.models import Terapia # Asegúrate que la importación de Terapia sea correcta
# from api.models import Usuario # No necesitas importar Usuario aquí si usas settings.AUTH_USER_MODEL
from django.db import models

class ChatConfig(models.Model):
    terapia = models.OneToOneField(
        Terapia,
        on_delete=models.CASCADE,
        related_name='chat_config'
    )
    chat_habilitado = models.BooleanField(default=True) # Cambiado a True por defecto (opcional)

    def __str__(self):
        return f"ChatConfig para Terapia {self.terapia.id} - Habilitado: {self.chat_habilitado}"

class Mensaje(models.Model):
    terapia = models.ForeignKey(
        Terapia,
        on_delete=models.CASCADE,
        related_name='mensajes_terapia' # Cambiado related_name para evitar conflicto
    )
    usuario = models.ForeignKey( # El que envía
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mensajes_enviados' # Cambiado related_name
    )
    # NUEVO CAMPO: Destinatario para mensajes privados
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, # Si el destinatario se borra, el mensaje queda sin destinatario explícito
        null=True,                 # Permite mensajes grupales (NULL)
        blank=True,                # Permite NULL en el admin y formularios
        related_name='mensajes_privados_recibidos' # Nuevo related_name
    )
    contenido = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['terapia', 'timestamp']),
            models.Index(fields=['terapia', 'recipient', 'timestamp']), # Índice para chats privados
        ]

    def __str__(self):
        if self.recipient:
            return f"Privado ({self.terapia.id}): {self.usuario.email} -> {self.recipient.email}: {self.contenido[:30]}"
        else:
            return f"Grupal ({self.terapia.id}): {self.usuario.email}: {self.contenido[:30]}"
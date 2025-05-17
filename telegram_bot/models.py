# telegram_bot/models.py

from django.db import models
from django.conf import settings # Para AUTH_USER_MODEL

class TelegramChat(models.Model):
    """Representa un chat de Telegram."""
    chat_id = models.BigIntegerField(unique=True, primary_key=True, help_text="Telegram Chat ID")
    # Si quieres vincular usuarios de Telegram con usuarios de tu app Django:
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='telegram_chat'
    )
    first_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    type = models.CharField(max_length=50, default='private', help_text="private, group, supergroup, or channel")
    is_active_support = models.BooleanField(default=True, help_text="Si este chat está activo para recibir soporte.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.username:
            return f"@{self.username} ({self.chat_id})"
        elif self.first_name:
            return f"{self.first_name} {self.last_name or ''} ({self.chat_id})"
        return str(self.chat_id)

class TelegramMessage(models.Model):
    """Representa un mensaje dentro de un chat de Telegram."""
    message_id = models.BigIntegerField(unique=True, primary_key=True, help_text="Telegram Message ID")
    chat = models.ForeignKey(TelegramChat, on_delete=models.CASCADE, related_name='messages')
    from_user_id = models.BigIntegerField(null=True, blank=True, help_text="Telegram User ID del remitente")
    text = models.TextField(null=True, blank=True)
    date = models.DateTimeField(help_text="Fecha en que se envió el mensaje (timestamp de Telegram)")
    is_from_bot = models.BooleanField(default=False, help_text="True si el mensaje fue enviado por nuestro bot")
    # Podrías añadir más campos como 'photo', 'document', 'sticker', etc. si los necesitas
    raw_update = models.JSONField(null=True, blank=True, help_text="El objeto de actualización completo de Telegram")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Msg {self.message_id} in Chat {self.chat.chat_id}"

    class Meta:
        ordering = ['date']
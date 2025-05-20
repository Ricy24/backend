# telegram_bot/models.py
from django.db import models
from django.conf import settings # Para AUTH_USER_MODEL
from django.utils import timezone # Para el expiry time

class TelegramChat(models.Model):
    """Representa un chat de Telegram."""
    chat_id = models.BigIntegerField(unique=True, primary_key=True, help_text="Telegram Chat ID")
    # Si un usuario de Django solo puede tener un chat de Telegram asociado, OneToOneField es correcto.
    # Si un usuario pudiera tener múltiples chats (menos común para este caso), sería ForeignKey.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, # Si el usuario Django se elimina, no eliminamos el chat, solo desvinculamos.
        null=True,
        blank=True,
        related_name='telegram_chat_profile' # Asegúrate que este related_name sea único
    )
    first_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    type = models.CharField(max_length=50, default='private', help_text="private, group, supergroup, or channel")
    # is_active_support ya no parece tan relevante si el bot es autónomo, pero puede quedar.
    # is_active_support = models.BooleanField(default=True, help_text="Si este chat está activo para recibir soporte.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Campos para verificación de email ---
    verification_code = models.CharField(max_length=10, null=True, blank=True, help_text="Código de verificación enviado al email.")
    verification_code_email = models.EmailField(null=True, blank=True, help_text="Email al que se envió el código.")
    verification_code_expiry = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora de expiración del código.")
    email_verified_at = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora de la última verificación exitosa del email para este chat.")

    # --- Para recordar la acción pendiente y la consulta original durante la verificación ---
    pending_action_after_verification = models.CharField(max_length=100, null=True, blank=True, help_text="Acción a realizar después de verificar.")
    original_query_for_verification = models.TextField(null=True, blank=True, help_text="Consulta original del usuario.")

    def __str__(self):
        if self.username:
            return f"@{self.username} ({self.chat_id})"
        elif self.first_name:
            return f"{self.first_name} {self.last_name or ''} ({self.chat_id})"
        return str(self.chat_id)

    def is_awaiting_verification_code(self):
        return self.verification_code and self.verification_code_expiry and self.verification_code_expiry > timezone.now()

    def clear_verification_fields(self):
        self.verification_code = None
        self.verification_code_email = None
        self.verification_code_expiry = None
        self.pending_action_after_verification = None
        self.original_query_for_verification = None
        # No limpiamos email_verified_at aquí, solo con una acción explícita de "desvincular" o si la verificación falla repetidamente.

class TelegramMessage(models.Model):
    """Representa un mensaje dentro de un chat de Telegram."""
    # message_id no puede ser primary_key=True si queremos permitir guardar mensajes del bot
    # que no tienen un message_id de Telegram único globalmente antes de enviarlos.
    # Usaremos el message_id de Telegram si viene del usuario, o un ID autogenerado si es del bot.
    # O, mejor, hacemos message_id único por chat: unique_together = ('chat', 'message_id_telegram')
    
    # Vamos a mantenerlo simple por ahora y asumir que message_id es el de Telegram.
    # Y para los mensajes del bot, si no tenemos un ID de Telegram, lo dejaremos null o generaremos uno.
    id = models.AutoField(primary_key=True) # ID interno de Django
    message_id_telegram = models.BigIntegerField(db_index=True, null=True, blank=True, help_text="Telegram Message ID (si es del usuario o respuesta del bot ya enviada)")
    chat = models.ForeignKey(TelegramChat, on_delete=models.CASCADE, related_name='messages')
    from_user_id = models.BigIntegerField(null=True, blank=True, help_text="Telegram User ID del remitente")
    text = models.TextField(null=True, blank=True)
    date = models.DateTimeField(help_text="Fecha en que se envió el mensaje (timestamp de Telegram o now() para el bot)")
    is_from_bot = models.BooleanField(default=False, help_text="True si el mensaje fue enviado por nuestro bot")
    raw_update = models.JSONField(null=True, blank=True, help_text="El objeto de actualización completo de Telegram (para mensajes de usuario)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']
        # Si quieres que message_id_telegram sea único por chat (recomendado si lo usas como identificador)
        unique_together = ('chat', 'message_id_telegram')


    def __str__(self):
        return f"Msg (TG:{self.message_id_telegram or 'BOT'}) in Chat {self.chat.chat_id} - Text: {self.text[:30] if self.text else '[No Text]'}"
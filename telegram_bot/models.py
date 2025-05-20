# telegram_bot/models.py
from django.db import models
from django.conf import settings # Para AUTH_USER_MODEL
from django.utils import timezone # Para el expiry time

class TelegramChat(models.Model):
    """Representa un chat de Telegram."""
    chat_id = models.BigIntegerField(unique=True, primary_key=True, help_text="Telegram Chat ID")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='telegram_chat_profile' # Asegúrate que este related_name sea único
    )
    first_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    type = models.CharField(max_length=50, default='private', help_text="private, group, supergroup, or channel")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Campos para el flujo de verificación de email ---
    verification_code = models.CharField(max_length=10, null=True, blank=True, help_text="Código de verificación enviado al email.")
    verification_code_email = models.EmailField(null=True, blank=True, help_text="Email al que se envió el código (y que se está verificando).")
    verification_code_expiry = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora de expiración del código.")
    email_verified_at = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora de la última verificación exitosa del email para este chat.")
    
    # --- Para recordar la acción pendiente y la consulta original durante la verificación ---
    pending_action_after_verification = models.CharField(max_length=100, null=True, blank=True, help_text="Acción a realizar después de verificar.")
    original_query_for_verification = models.TextField(null=True, blank=True, help_text="Consulta original del usuario que disparó la necesidad de verificación.")

    # --- NUEVO CAMPO para el flujo conversacional de pedir email ---
    is_awaiting_email_input = models.BooleanField(default=False, help_text="True si el bot está esperando que el usuario ingrese su email.")

    def __str__(self):
        if self.username:
            return f"@{self.username} ({self.chat_id})"
        elif self.first_name:
            return f"{self.first_name} {self.last_name or ''} ({self.chat_id})"
        return str(self.chat_id)

    def is_awaiting_verification_code_state(self): # Renombrado para evitar confusión con el campo del modelo
        """Devuelve True si hay un código de verificación activo y no expirado."""
        return bool(self.verification_code and self.verification_code_expiry and self.verification_code_expiry > timezone.now())

    def clear_verification_fields(self):
        """Limpia todos los campos relacionados con un proceso de verificación en curso o un estado de espera."""
        self.verification_code = None
        self.verification_code_email = None # Limpiar el email que se estaba intentando verificar
        self.verification_code_expiry = None
        self.pending_action_after_verification = None
        self.original_query_for_verification = None
        self.is_awaiting_email_input = False # Importante resetear este estado también
        # No limpiamos email_verified_at ni self.user aquí, eso se maneja con /desvincular_email
        # o si una nueva verificación exitosa sobrescribe self.user.

class TelegramMessage(models.Model):
    """Representa un mensaje dentro de un chat de Telegram."""
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
        # Asegura que no guardemos el mismo mensaje de Telegram dos veces para el mismo chat
        unique_together = ('chat', 'message_id_telegram')


    def __str__(self):
        # Pequeña mejora para el string si el texto es muy largo o no existe
        text_preview = "[No Text]"
        if self.text:
            text_preview = (self.text[:30] + '...') if len(self.text) > 30 else self.text
        
        tg_id_display = f"TG:{self.message_id_telegram}" if self.message_id_telegram else "BOT_MSG"
        
        return f"Msg (ID:{self.id}, {tg_id_display}) in Chat {self.chat.chat_id} - Text: {text_preview}"
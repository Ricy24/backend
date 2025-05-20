# telegram_bot/admin.py

from django.contrib import admin
from .models import TelegramChat, TelegramMessage

@admin.register(TelegramChat)
class TelegramChatAdmin(admin.ModelAdmin):
    list_display = (
        'chat_id',
        'user',  # Muestra el __str__ del modelo Usuario (que es el email)
        'username',
        'first_name',
        'type',
        # 'is_active_support', # Comentado o eliminado si ya no está en el modelo
        'email_verified_at', # Nuevo campo
        'updated_at'
    )
    search_fields = (
        'chat_id',
        'username',
        'first_name',
        'last_name',
        'user__email', # Para buscar por el email del usuario Django vinculado
        'verification_code_email' # Nuevo campo
    )
    list_filter = (
        'type',
        # 'is_active_support', # Comentado o eliminado
        'created_at',
        'email_verified_at' # Nuevo campo
    )
    raw_id_fields = ('user',) # Bueno para seleccionar usuarios si tienes muchos
    readonly_fields = ('created_at', 'updated_at', 'email_verified_at') # Campos que no se editan manualmente

    fieldsets = (
        (None, {
            'fields': ('chat_id', 'user', 'type', 'username', 'first_name', 'last_name')
        }),
        ('Verificación de Email', {
            'classes': ('collapse',), # Para que aparezca colapsado
            'fields': ('verification_code_email', 'verification_code', 'verification_code_expiry', 'email_verified_at', 'pending_action_after_verification', 'original_query_for_verification'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

@admin.register(TelegramMessage)
class TelegramMessageAdmin(admin.ModelAdmin):
    list_display = (
        'id', # El ID interno de Django
        'message_id_telegram', # El ID del mensaje de Telegram
        'chat',
        'from_user_id',
        'get_short_text',
        'date',
        'is_from_bot'
    )
    search_fields = (
        'text',
        'chat__chat_id',
        'chat__username',
        'message_id_telegram' # Para buscar por el ID de mensaje de Telegram
    )
    list_filter = ('is_from_bot', 'date', 'chat__type') # Filtrar por tipo de chat
    readonly_fields = ('created_at', 'raw_update') # Raw update no debería ser editable
    raw_id_fields = ('chat',) # Para seleccionar chats

    def get_short_text(self, obj):
        if obj.text:
            return (obj.text[:75] + '...') if len(obj.text) > 75 else obj.text
        return "[Sin Texto]" # Opcional: manejar mensajes sin texto como fotos/stickers
    get_short_text.short_description = 'Texto del Mensaje'
# telegram_bot/admin.py

from django.contrib import admin
from .models import TelegramChat, TelegramMessage

@admin.register(TelegramChat)
class TelegramChatAdmin(admin.ModelAdmin):
    list_display = ('chat_id', 'user', 'username', 'first_name', 'type', 'is_active_support', 'updated_at')
    search_fields = ('chat_id', 'username', 'first_name', 'last_name', 'user__email') # Asumiendo que tu Usuario tiene email
    list_filter = ('type', 'is_active_support', 'created_at')
    raw_id_fields = ('user',)

@admin.register(TelegramMessage)
class TelegramMessageAdmin(admin.ModelAdmin):
    list_display = ('message_id', 'chat', 'from_user_id', 'get_short_text', 'date', 'is_from_bot')
    search_fields = ('text', 'chat__chat_id', 'chat__username')
    list_filter = ('is_from_bot', 'date')
    readonly_fields = ('created_at',)

    def get_short_text(self, obj):
        return (obj.text[:75] + '...') if obj.text and len(obj.text) > 75 else obj.text
    get_short_text.short_description = 'Text'
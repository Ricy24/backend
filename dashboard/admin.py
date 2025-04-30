from django.contrib import admin
from .models import Mood, SupportGroup, PsychologicalTest, DiaryEntry, DiaryConversation, SleepLog, UserStreak
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

# --- Configuraciones del Admin Site ---
admin.site.site_header = "Administración de Bienestar Mental"
admin.site.site_title = "Portal de Administración"
admin.site.index_title = "Bienvenido al Portal de Administración de Bienestar"

# --- Inlines ---
class DiaryConversationInline(admin.TabularInline):
    model = DiaryConversation
    fields = ('role', 'content', 'timestamp')
    readonly_fields = ('timestamp',)
    extra = 0
    ordering = ('timestamp',)
    can_delete = True

# --- ModelAdmins ---
@admin.register(Mood)
class MoodAdmin(admin.ModelAdmin):
    list_display = ('user', 'mood', 'timestamp', 'short_description')
    list_filter = ('mood', 'timestamp', 'user')
    search_fields = ('user__email', 'description')
    readonly_fields = ('timestamp',)
    date_hierarchy = 'timestamp'
    ordering = ('-timestamp',)

    @admin.display(description='Descripción Corta')
    def short_description(self, obj):
        if obj.description:
            return obj.description[:50] + '...' if len(obj.description) > 50 else obj.description
        return '-'

@admin.register(SupportGroup)
class SupportGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'time', 'duration', 'user_count')
    list_filter = ('time',)
    search_fields = ('name',)
    filter_horizontal = ('users',)
    ordering = ('time',)

    @admin.display(description='Nº Usuarios')
    def user_count(self, obj):
        return obj.users.count()

@admin.register(PsychologicalTest)
class PsychologicalTestAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'score', 'completed_at')
    list_filter = ('name', 'completed_at', 'user')
    search_fields = ('user__email', 'name')
    readonly_fields = ('completed_at',)
    date_hierarchy = 'completed_at'
    ordering = ('-completed_at',)

@admin.register(DiaryEntry)
class DiaryEntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'day_name', 'title', 'is_empty', 'conversation_count')
    list_filter = ('date', 'day_name', 'is_empty', 'user')
    search_fields = ('user__email', 'title', 'content')
    readonly_fields = ('date', 'day_name')
    date_hierarchy = 'date'
    ordering = ('-date',)
    inlines = [DiaryConversationInline]

    @admin.display(description='Nº Conversaciones')
    def conversation_count(self, obj):
        return obj.conversations.count()

@admin.register(UserStreak)
class UserStreakAdmin(admin.ModelAdmin):
    list_display = ('get_user_email', 'current_streak', 'last_entry_date')
    search_fields = ('user__email',)
    readonly_fields = ('user',)
    list_editable = ('current_streak', 'last_entry_date')
    ordering = ('user__email',)

    def get_user_email(self, obj):
        return obj.user.email
    get_user_email.short_description = 'Email del usuario'

@admin.register(SleepLog)
class SleepLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'hours_slept', 'sleep_quality', 'timestamp')
    list_filter = ('date', 'sleep_quality', 'user')
    search_fields = ('user__email',)
    readonly_fields = ('timestamp',)
    date_hierarchy = 'date'
    ordering = ('-date',)
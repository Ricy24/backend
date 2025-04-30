# therapy/admin.py
from django.contrib import admin
from .models import (
    Category, InitialScreeningAssessment, EmotionalProfile,
    EmotionalPath, Challenge, UserChallenge, UserPathProgress, DailyComponent
)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)
    list_filter = ('name',)
    ordering = ('name',)

@admin.register(InitialScreeningAssessment)
class InitialScreeningAssessmentAdmin(admin.ModelAdmin):
    list_display = ('user', 'terapia', 'therapy_type', 'completed', 'created_at')
    list_filter = ('therapy_type', 'completed', 'created_at')
    search_fields = ('user__email',)
    readonly_fields = ('responses', 'scores', 'created_at')
    list_per_page = 20

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'terapia')

@admin.register(EmotionalProfile)
class EmotionalProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'terapia', 'therapy_type', 'created_at', 'updated_at')
    list_filter = ('therapy_type', 'created_at')
    search_fields = ('user__email',)
    readonly_fields = ('scores', 'created_at', 'updated_at')
    list_per_page = 20

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'terapia')

@admin.register(EmotionalPath)
class EmotionalPathAdmin(admin.ModelAdmin):
    list_display = ('user', 'terapia', 'category', 'level', 'is_active', 'created_at')
    list_filter = ('is_active', 'level', 'category')
    search_fields = ('user__email', 'category__name')
    list_per_page = 20

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'terapia', 'category')

@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'level', 'tools', 'mode_collaborative', 'reveal_after_days')
    list_filter = ('category', 'level', 'mode_collaborative', 'tools')
    search_fields = ('title', 'description')
    fieldsets = (
        (None, {
            'fields': (
                'title', 'category', 'description', 'instructions', 'level',
                'tools', 'mode_collaborative', 'duration_minutes', 'reveal_after_days'
            )
        }),
    )

@admin.register(UserChallenge)
class UserChallengeAdmin(admin.ModelAdmin):
    list_display = ('user', 'challenge', 'is_completed', 'available_date', 'reveal_date')
    list_filter = ('is_completed', 'available_date', 'reveal_date')
    search_fields = ('user__email', 'challenge__title')

@admin.register(UserPathProgress)
class UserPathProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'terapia', 'current_level', 'completed_challenges', 'last_level_up')
    list_filter = ('current_level',)
    search_fields = ('user__email',)
    list_per_page = 20

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'terapia')

@admin.register(DailyComponent)
class DailyComponentAdmin(admin.ModelAdmin):
    list_display = ('user', 'terapia', 'component_type', 'date', 'completed_at')
    list_filter = ('component_type', 'date')
    search_fields = ('user__email',)
    list_per_page = 20

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'terapia')
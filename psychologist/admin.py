# psychologist/admin.py
from django.contrib import admin
from django import forms
from .models import PsychologistProfile, Availability, Specialty, Language, Certification
from api.models import Usuario

class CertificationInline(admin.TabularInline):
    model = Certification
    extra = 1

class PsychologistProfileAdminForm(forms.ModelForm):
    class Meta:
        model = PsychologistProfile
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = Usuario.objects.filter(is_psychologist=True)

@admin.register(PsychologistProfile)
class PsychologistProfileAdmin(admin.ModelAdmin):
    form = PsychologistProfileAdminForm
    inlines = [CertificationInline]
    list_display = (
        'user_email',
        'user_nombre',
        'offers_free_30min_session',
        'years_experience',
        'therapeutic_approach',
        'created_at',
        'updated_at',
    )
    list_filter = (
        'offers_free_30min_session',
        'created_at',
        'updated_at',
        'languages',
        'therapeutic_approach',
    )
    search_fields = (
        'user__email',
        'user__nombre',
        'bio',
        'therapeutic_approach',
    )
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Información del Usuario', {
            'fields': ('user',)
        }),
        ('Detalles Profesionales', {
            'fields': (
                'specialties',
                'bio',
                'languages',
                'years_experience',
                'therapeutic_approach',
                'offers_free_30min_session',
            )
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

    def user_nombre(self, obj):
        return obj.user.nombre or 'Sin nombre'
    user_nombre.short_description = 'Nombre'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        'psychologist_email',
        'psychologist_nombre',
        'day_of_week',
        'start_time',
        'end_time',
        'created_at',
        'updated_at',
    )
    list_filter = (
        'day_of_week',
        'created_at',
        'updated_at',
    )
    search_fields = (
        'psychologist__email',
        'psychologist__nombre',
        'day_of_week',
    )
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Información de Disponibilidad', {
            'fields': ('psychologist', 'day_of_week', 'start_time', 'end_time')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def psychologist_email(self, obj):
        return obj.psychologist.email
    psychologist_email.short_description = 'Email'

    def psychologist_nombre(self, obj):
        return obj.psychologist.nombre or 'Sin nombre'
    psychologist_nombre.short_description = 'Nombre'

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['psychologist'].queryset = Usuario.objects.filter(is_psychologist=True)
        return form

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('psychologist')

@admin.register(Specialty)
class SpecialtyAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
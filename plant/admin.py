from django.contrib import admin
from django.utils.html import format_html
from .models import Plant, PlantDesign

@admin.register(PlantDesign)
class PlantDesignAdmin(admin.ModelAdmin):
    list_display = ['name', 'design_key', 'plant_type', 'is_active', 'preview_image']
    list_filter = ['plant_type', 'is_active']
    search_fields = ['name', 'design_key', 'description']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['is_active']

    def preview_image(self, obj):
        if obj.image_url:
            return format_html('<img src="{}" style="max-height: 50px;"/>', obj.image_url)
        return '(Sin imagen)'
    preview_image.short_description = 'Vista previa'

@admin.register(Plant)
class PlantAdmin(admin.ModelAdmin):
    list_display = ['name', 'terapia_info', 'type', 'design', 'level', 'current_streak', 'plant_status', 'last_care_date']
    list_filter = ['type', 'level', 'is_alive']
    search_fields = ['name', 'terapia__id']
    readonly_fields = ['created_at', 'updated_at', 'current_streak', 'last_care_date']
    
    fieldsets = [
        ('Información Básica', {
            'fields': ['name', 'terapia', 'type', 'design']
        }),
        ('Estado y Progreso', {
            'fields': ['level', 'current_streak', 'is_alive', 'last_care_date']
        }),
        ('Información del Sistema', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        })
    ]

    def terapia_info(self, obj):
        """Muestra información de la terapia con formato HTML."""
        if obj.terapia:
            return format_html(
                '<strong>ID:</strong> {} | <strong>Tipo:</strong> {}',
                obj.terapia.id,
                obj.terapia.tipo
            )
        return '-'
    terapia_info.short_description = 'Terapia'
    terapia_info.admin_order_field = 'terapia__id'

    def plant_status(self, obj):
        """Muestra un indicador visual del estado de la planta."""
        if obj.is_alive:
            return format_html(
                '<span style="color: green;">●</span> Viva'
            )
        return format_html(
            '<span style="color: red;">●</span> Necesita Cuidados'
        )
    plant_status.short_description = 'Estado'

    def save_model(self, request, obj, form, change):
        """Asegura que el tipo de planta coincida con el tipo de terapia."""
        if obj.terapia and not change:  # Solo para nuevas plantas
            if obj.terapia.tipo == 'familiar':
                obj.type = 'arbol'
            else:
                obj.type = 'planta'
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        """Hace que ciertos campos sean de solo lectura después de la creación."""
        if obj:  # Si el objeto ya existe
            return self.readonly_fields + ['type']  # No permitir cambiar el tipo después de crear
        return self.readonly_fields

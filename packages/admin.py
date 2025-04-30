# packages/admin.py

from django.contrib import admin
from django.utils.html import format_html # Para formatear JSON
from django.utils.safestring import mark_safe # Para formatear JSON
import json # Para formatear JSON
from .models import DiscountCode, SessionPricingTier, Purchase

# Registro de DiscountCode (sin cambios, ya estaba bien)
@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_percentage', 'is_active', 'valid_until', 'uses_display', 'max_uses')
    search_fields = ('code',)
    list_filter = ('is_active',)
    list_editable = ('is_active',)
    ordering = ('-valid_until', 'code')

    def uses_display(self, obj):
        if obj.max_uses is not None:
            return f"{obj.uses}/{obj.max_uses}"
        return f"{obj.uses}/∞"
    uses_display.short_description = "Usos"

    actions = ['mark_active', 'mark_inactive']

    def mark_active(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, "Los códigos seleccionados han sido activados.")
    mark_active.short_description = "Activar códigos seleccionados"

    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, "Los códigos seleccionados han sido desactivados.")
    mark_inactive.short_description = "Desactivar códigos seleccionados"

# Registro de SessionPricingTier (sin cambios, ya estaba bien)
@admin.register(SessionPricingTier)
class SessionPricingTierAdmin(admin.ModelAdmin):
    list_display = ('therapy_type', 'session_range', 'price_per_session', 'is_active')
    search_fields = ('therapy_type',)
    list_filter = ('therapy_type', 'is_active')
    list_editable = ('is_active',)
    ordering = ('therapy_type', 'min_sessions')

    def session_range(self, obj):
        if obj.max_sessions:
            return f"{obj.min_sessions} - {obj.max_sessions}"
        return f"{obj.min_sessions}+"
    session_range.short_description = "Rango de sesiones"

# Registro de Purchase (ACTUALIZADO)
@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = (
        'reference_code',
        'user_email', # Mostramos email para claridad
        'payment_status', # Estado es crucial
        'transaction_id', # ID de transacción visible
        'payment_provider', # Proveedor visible
        'final_price',
        'purchase_date',
    )
    search_fields = (
        'user__email',
        'reference_code',
        'transaction_id', # Búsqueda por Tx ID
        'payment_provider', # Búsqueda por proveedor
        'therapy_type_purchased'
    )
    list_filter = (
        'payment_status',
        'payment_provider', # Filtro por proveedor
        'therapy_type_purchased',
        'purchase_date'
    )
    readonly_fields = (
        'purchase_date',
        'reference_code',
        'base_price',
        'discount_applied_amount',
        'final_price',
        'user_email', # Helper readonly
        'transaction_id', # Hacerlos readonly aquí también
        'payment_provider',
        'display_payment_details', # Mostrar JSON formateado
        'error_message',
    )
    ordering = ('-purchase_date',)
    list_per_page = 25 # Ajusta si quieres ver más/menos por página

    # Organización del formulario de detalle ACTUALIZADA
    fieldsets = (
        ('Información del usuario', {
            'fields': ('user_email', 'user') # Mostrar email y enlace al usuario
        }),
        ('Detalles de la compra', {
            'fields': ('terapia', 'therapy_type_purchased', 'purchased_session_count', 'remaining_sessions')
        }),
        ('Detalles del precio', {
            'fields': ('price_per_session_applied', 'base_price', 'discount_code', 'discount_applied_amount', 'final_price')
        }),
        ('Estado y referencias del pago', { # Sección renombrada y ampliada
            'fields': (
                'payment_status',
                'purchase_date',
                'reference_code',
                'transaction_id',     # <-- Añadido
                'payment_provider',   # <-- Añadido
                'display_payment_details', # <-- Usamos el helper para JSON
                'error_message'       # <-- Añadido
                )
        }),
    )

    # Eliminamos acciones peligrosas que cambian el estado sin llamar a update_payment_status
    # Si las necesitas, asegúrate de que llamen a la lógica correcta.
    # actions = ['mark_completed', 'mark_failed']

    # def mark_completed(self, request, queryset):
    #     # CUIDADO: Esto NO llama a update_payment_status ni crea el Payment
    #     # queryset.update(payment_status='completed')
    #     self.message_user(request, "Acción deshabilitada temporalmente. Modificar estado individualmente si es necesario.", level='warning')
    # mark_completed.short_description = "Marcar como completadas (DESHABILITADO)"

    # def mark_failed(self, request, queryset):
    #     # CUIDADO: Esto NO llama a update_payment_status
    #     # queryset.update(payment_status='failed')
    #     self.message_user(request, "Acción deshabilitada temporalmente. Modificar estado individualmente si es necesario.", level='warning')
    # mark_failed.short_description = "Marcar como fallidas (DESHABILITADO)"

    @admin.display(description='Usuario Email')
    def user_email(self, obj):
        """Muestra el email del usuario para fácil identificación."""
        if obj.user:
            return obj.user.email
        return '-'

    @admin.display(description='Detalles del Pago (JSON)')
    def display_payment_details(self, obj):
        """Muestra el campo JSON payment_details formateado."""
        if obj.payment_details:
            try:
                # Formatear el JSON para legibilidad
                formatted_json = json.dumps(obj.payment_details, indent=4, ensure_ascii=False)
                # Usar <pre> para mantener el formato y saltos de línea
                return format_html('<pre>{}</pre>', formatted_json)
            except TypeError:
                return f"No se pudo formatear: {obj.payment_details}"
        return 'N/A'

    # Optimización de consultas (ya la tenías, está bien)
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'terapia', 'discount_code')
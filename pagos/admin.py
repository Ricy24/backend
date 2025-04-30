# pagos/admin.py

from django.contrib import admin
from django.utils.html import format_html # Para enlaces opcionales
from django.urls import reverse # Para enlaces opcionales
from .models import Payment, PaymentMethod

# Opcional: Si quieres enlazar al admin de Purchase desde Payment
# from packages.models import Purchase


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Configuración del Admin para el modelo Payment.
    """
    list_display = (
        'transaction_id',
        'user_email', # Campo personalizado para mostrar email
        'display_purchase_link', # Campo personalizado para enlace a Purchase (opcional)
        'amount',
        'currency',
        'status',
        'provider',
        'method',
        'created_at'
    )
    list_filter = ('status', 'provider', 'currency', 'created_at')
    search_fields = (
        'transaction_id',
        'user__email', # Buscar por email del usuario relacionado
        'description',
        # Opcional: Si tienes ForeignKey a Purchase y quieres buscar por su reference_code
        # 'purchase__reference_code',
    )
    readonly_fields = (
        'user',
        # 'purchase', # Hacerlo readonly si tienes el enlace
        'transaction_id',
        'provider',
        'amount',
        'currency',
        'created_at',
        'method',
        'card_last_four',
        'display_purchase_link', # También en readonly si lo usas
    )
    date_hierarchy = 'created_at'
    list_per_page = 25

    fieldsets = (
        (None, {
            'fields': ('user', 'display_purchase_link', 'transaction_id', 'status', 'description')
        }),
        ('Detalles del Pago', {
            'fields': ('amount', 'currency', 'provider', 'method', 'card_last_four'),
            # 'classes': ('collapse',) # Puedes descomentar para que se oculte por defecto
        }),
        ('Fecha', {
            'fields': ('created_at',)
        }),
    )

    @admin.display(description='Usuario Email')
    def user_email(self, obj):
        """Muestra el email del usuario."""
        if obj.user:
            return obj.user.email
        return '-'

    @admin.display(description='Compra Asociada')
    def display_purchase_link(self, obj):
        """
        Muestra un enlace a la página de admin de la Purchase asociada, si existe.
        REQUIERE que tu modelo Payment tenga un campo ForeignKey llamado 'purchase'
        que apunte al modelo Purchase. Si no lo tiene, elimina este método
        y su uso en list_display, readonly_fields y fieldsets.
        """
        if hasattr(obj, 'purchase') and obj.purchase:
            # Asegúrate que 'admin:packages_purchase_change' es la ruta correcta
            # El formato es 'admin:<app_label>_<model_name>_change'
            try:
                purchase_admin_url = reverse('admin:packages_purchase_change', args=[obj.purchase.pk])
                # Muestra el reference_code como texto del enlace
                return format_html('<a href="{}">{}</a>', purchase_admin_url, obj.purchase.reference_code)
            except Exception:
                # Si la URL no se puede generar (ej. app no registrada o nombre incorrecto)
                return f"ID Compra: {obj.purchase.pk} (Error en enlace)"
        return "N/A"

@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    """
    Configuración del Admin para el modelo PaymentMethod.
    """
    list_display = (
        'user_email', # Campo personalizado
        'provider',
        'card_brand',
        'card_last_four',
        'payment_method_id', # El ID/token del proveedor
        'created_at'
    )
    list_filter = ('provider', 'card_brand')
    search_fields = ('user__email', 'payment_method_id', 'card_last_four')
    readonly_fields = (
        'user',
        'provider',
        'card_last_four',
        'card_brand',
        'payment_method_id',
        'created_at'
    )
    list_per_page = 25

    @admin.display(description='Usuario Email')
    def user_email(self, obj):
        """Muestra el email del usuario."""
        if obj.user:
            return obj.user.email
        return '-'

# Asegúrate que esta app ('pagos') esté añadida a tu INSTALLED_APPS en settings.py
# y que hayas corrido las migraciones correspondientes.
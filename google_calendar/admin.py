# En tu_app/admin.py (reemplaza 'tu_app' con el nombre real de tu app)

from django.contrib import admin
from .models import CalendarEvent # Asegúrate que la ruta de importación sea correcta

@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    """
    Admin interface for the CalendarEvent model.

    Provides filtering, searching, and detailed views for calendar events.

    **Important Warning:**
    Creating or modifying events of type 'therapy' or 'group' directly via the admin
    interface will bypass crucial business logic present in the API views, such as:
        - Psychologist availability checks.
        - Conflict detection with other sessions.
        - Free session limitations and checks.
        - Deduction of sessions from purchased packages.
        - Refund logic upon cancellation (returning sessions to packages).
        - Generation/validation of Jitsi Meet links based on the session day.

    Use the admin interface primarily for viewing, data correction for non-critical fields,
    or managing 'personal'/'special' event types if necessary. Complex scheduling and
    cancellations involving therapies should ideally be handled through the application's
    frontend/API to ensure all business rules are applied correctly.
    """

    list_display = (
        'title',
        'display_user',        # Muestra el usuario de forma más legible
        'display_psychologist',# Muestra el psicólogo de forma más legible
        'type',
        'start_time',
        'end_time',
        'terapia',
        'event_id',            # Útil para referencia, pero quizás menos prioritario en la lista
        'created_at',
    )

    list_filter = (
        'type',
        'start_time',
        'created_at',
        ('user', admin.RelatedOnlyFieldListFilter),        # Filtro eficiente para FKs con muchos objetos
        ('psychologist', admin.RelatedOnlyFieldListFilter),# Filtro eficiente
        'terapia',
    )

    search_fields = (
        'title',
        'description',
        'event_id',
        'user__username',       # Buscar por nombre de usuario
        'user__email',          # Buscar por email de usuario
        'user__nombre',         # Asumiendo que tu modelo User tiene un campo 'nombre'
        'psychologist__username',
        'psychologist__email',
        'psychologist__nombre', # Asumiendo que tu modelo User tiene un campo 'nombre'
        'terapia__id',          # Buscar por ID de Terapia puede ser útil
    )

    readonly_fields = (
        'event_id',             # Generalmente no debería cambiarse manualmente
        'jitsi_meet_link',      # Gestionado por la lógica de la vista/modelo
        'jitsi_meet_room',      # Gestionado por la lógica de la vista/modelo
        'created_at',
        'updated_at',
    )

    # Usar raw_id_fields es mejor para ForeignKeys con potencialmente muchos objetos (como User)
    # Evita dropdowns gigantes y mejora el rendimiento.
    raw_id_fields = ('user', 'psychologist', 'terapia')

    # Organizar los campos en el formulario de edición/creación
    fieldsets = (
        (None, {
            'fields': ('title', 'type', 'description')
        }),
        ('Participants & Context', {
            'fields': ('user', 'psychologist', 'terapia')
        }),
        ('Timing', {
            'fields': ('start_time', 'end_time')
        }),
        ('Technical Details (Read Only)', {
            'classes': ('collapse',), # Opcional: ocultar esta sección por defecto
            'fields': ('event_id', 'jitsi_meet_link', 'jitsi_meet_room')
        }),
        ('Audit Trail (Read Only)', {
            'classes': ('collapse',), # Opcional: ocultar esta sección por defecto
            'fields': ('created_at', 'updated_at')
        }),
    )

    # Métodos para mejorar la visualización en list_display
    @admin.display(description='User', ordering='user')
    def display_user(self, obj):
        if obj.user:
            # Intenta mostrar nombre si existe, si no username, si no ID
            return getattr(obj.user, 'nombre', None) or obj.user.username or f"ID: {obj.user.id}"
        return '-'

    @admin.display(description='Psychologist', ordering='psychologist')
    def display_psychologist(self, obj):
        if obj.psychologist:
            return getattr(obj.psychologist, 'nombre', None) or obj.psychologist.username or f"ID: {obj.psychologist.id}"
        return '-'

    # Si necesitaras sobreescribir el guardado o borrado (¡con mucho cuidado!)
    # def save_model(self, request, obj, form, change):
    #     # Aquí podrías añadir lógica extra, pero es complejo replicar las vistas
    #     super().save_model(request, obj, form, change)

    # def delete_model(self, request, obj):
    #     # Aquí podrías intentar replicar la lógica de devolución de sesiones,
    #     # pero es propenso a errores y desincronización con las vistas.
    #     super().delete_model(request, obj)

# Asegúrate de que este archivo admin.py esté en una app que esté listada
# en tu INSTALLED_APPS en settings.py.
# También, si el modelo Terapia está en otra app (ej: 'api'), asegúrate de
# que esa app también esté registrada y que la relación ForeignKey funcione correctamente.
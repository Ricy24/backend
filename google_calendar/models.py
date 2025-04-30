from django.conf import settings
from django.db import models
import uuid

class CalendarEvent(models.Model):
    EVENT_TYPES = (
        ('free_session', 'Sesión Gratuita'),
        ('therapy', 'Terapia'),
        ('group', 'Grupo de Apoyo'),
        ('personal', 'Personal'),
        ('special', 'Especial'),
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='calendar_events'
    )
    
    psychologist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='psychologist_events'
    )
    
    terapia = models.ForeignKey(
        'api.Terapia',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='calendar_events'
    )

    purchase_used = models.ForeignKey(
        'packages.Purchase',
        on_delete=models.SET_NULL, # Opcional: Si se borra la compra, no borrar el evento
        null=True,
        blank=True,
        related_name='calendar_events_used_in' # Nombre de relación inversa
    )
    
    event_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=200)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    type = models.CharField(max_length=20, choices=EVENT_TYPES, default='personal')
    description = models.TextField(blank=True, null=True)
    jitsi_meet_link = models.URLField(max_length=500, blank=True, null=True)  # Enlace de Jitsi Meet
    jitsi_meet_room = models.CharField(max_length=100, blank=True, null=True)  # Nombre único de la sala
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"{self.title} ({self.user.username}) - {self.start_time}"

    def generate_jitsi_meet_link(self):
        """Genera un enlace único de Jitsi Meet para la sesión."""
        if not self.jitsi_meet_room:
            # Crear un nombre de sala único basado en el event_id y un UUID
            self.jitsi_meet_room = f"TherapySession-{self.event_id}-{uuid.uuid4().hex[:8]}"
        jitsi_base_url = getattr(settings, 'JITSI_MEET_BASE_URL', 'https://meet.jit.si')
        self.jitsi_meet_link = f"{jitsi_base_url}/{self.jitsi_meet_room}"
        self.save()
        return self.jitsi_meet_link
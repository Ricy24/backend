# therapy/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from api.models import Terapia
from multiselectfield import MultiSelectField

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"

    def __str__(self):
        return self.name

class EmotionalPath(models.Model):
    """
    Representa una ruta emocional activa para un usuario (ej. Depresión, Ansiedad).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='emotional_paths'
    )
    terapia = models.ForeignKey(
        Terapia,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='emotional_paths'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='emotional_paths'
    )
    level = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'terapia', 'category')
        verbose_name = "Ruta Emocional"
        verbose_name_plural = "Rutas Emocionales"

    def __str__(self):
        return f"{self.user.email} - {self.category.name} (Nivel {self.level})"

class Challenge(models.Model):
    """
    Define un reto emocional con sus características.
    """
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='challenges'
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    instructions = models.TextField(blank=True)
    level = models.PositiveIntegerField(default=1)
    type = models.CharField(
        max_length=20,
        choices=[
            ('text', 'Texto'),
            ('audio', 'Audio'),
            ('drawing', 'Dibujo'),
            ('letter', 'Carta'),
        ],
        default='text'
    )
    component_frontend = models.CharField(
        max_length=100,
        blank=True,
        help_text="Componente frontend asociado (ej. TextChallenge, AudioRecorder)"
    )
    mode_collaborative = models.BooleanField(
        default=False,
        help_text="Indica si el reto es colaborativo (para parejas/familias)"
    )
    duration_minutes = models.PositiveIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    TOOLS_CHOICES = [
        ('text', 'Texto'),
        ('drawing', 'Dibujo'),
        ('photo', 'Foto'),
        ('video', 'Video'),
        ('reflection', 'Reflexión'),
        ('letter', 'Carta'),
    ]
    tools = models.CharField(
        max_length=15,
        choices=TOOLS_CHOICES,
        help_text="Herramienta requerida para el reto (texto, dibujo, foto, video, reflexión, carta)"
    )
    reveal_after_days = models.PositiveIntegerField(
        default=0,
        help_text="Días después de completado para mostrar el resultado/reflexión/carta (0 = inmediato)"
    )

    class Meta:
        verbose_name = "Reto"
        verbose_name_plural = "Retos"

    def __str__(self):
        return f"{self.title} ({self.category.name}, Nivel {self.level})"

    def clean(self):
        if not self.tools or self.tools not in dict(self.TOOLS_CHOICES):
            raise ValidationError("Selecciona una herramienta válida.")
        # Para reflexión/carta, reveal_after_days debe ser > 0
        if self.tools in ['reflection', 'letter'] and self.reveal_after_days == 0:
            raise ValidationError("Debes definir en cuántos días se revela la reflexión o carta.")
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

class UserChallenge(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_challenges'
    )
    terapia = models.ForeignKey(
        Terapia,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='user_challenges'
    )
    challenge = models.ForeignKey(
        Challenge,
        on_delete=models.CASCADE,
        related_name='user_challenges'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    collaborative_recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collaborative_challenges',
        help_text="Usuario destinatario para retos colaborativos"
    )
    available_date = models.DateField(default=timezone.now, help_text="Fecha en la que el reto está disponible para el usuario")
    reveal_date = models.DateField(null=True, blank=True, help_text="Fecha en la que el resultado se muestra al usuario (para reflexiones/cartas)")
    content = models.JSONField(null=True, blank=True, help_text="Datos del reto completado (texto, URL de archivo, etc.)")

    class Meta:
        unique_together = ('user', 'terapia', 'challenge', 'assigned_at')
        verbose_name = "Reto de Usuario"
        verbose_name_plural = "Retos de Usuarios"

    def __str__(self):
        return f"{self.user.email} - {self.challenge.title} ({'Completado' if self.is_completed else 'Asignado'})"
    
class UserPathProgress(models.Model):
    """
    Lleva el progreso global de un usuario en sus rutas emocionales.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='path_progress'
    )
    terapia = models.ForeignKey(
        Terapia,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='path_progress'
    )
    current_level = models.PositiveIntegerField(default=1)
    completed_challenges = models.PositiveIntegerField(default=0)
    last_level_up = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'terapia')
        verbose_name = "Progreso de Ruta"
        verbose_name_plural = "Progresos de Rutas"

    def __str__(self):
        return f"{self.user.email} - Nivel {self.current_level}"

class DailyComponent(models.Model):
    """
    Registra la finalización de componentes diarios (diario, meditación).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='daily_components'
    )
    terapia = models.ForeignKey(
        Terapia,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='daily_components'
    )
    component_type = models.CharField(
        max_length=20,
        choices=[
            ('diary', 'Diario Emocional'),
            ('meditation', 'Meditación Guiada'),
        ]
    )
    completed_at = models.DateTimeField(auto_now_add=True)
    date = models.DateField(default=timezone.now)

    class Meta:
        unique_together = ('user', 'terapia', 'component_type', 'date')
        verbose_name = "Componente Diario"
        verbose_name_plural = "Componentes Diarios"

    def __str__(self):
        return f"{self.user.email} - {self.get_component_type_display()} ({self.date})"

# Modelos existentes (sin cambios)
class InitialScreeningAssessment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='screening_assessments'
    )
    terapia = models.ForeignKey(
        Terapia,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='screening_assessments'
    )
    therapy_type = models.CharField(
        max_length=20,
        choices=[('individual', 'Individual'), ('couple', 'Pareja'), ('family', 'Familiar')],
        default='individual'
    )
    responses = models.JSONField()
    scores = models.JSONField(default=dict)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'terapia', 'therapy_type')
        verbose_name = "Evaluación Inicial"
        verbose_name_plural = "Evaluaciones Iniciales"

    def __str__(self):
        return f"Evaluación para {self.user.email} ({self.therapy_type})"

class EmotionalProfile(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='emotional_profiles'
    )
    terapia = models.ForeignKey(
        Terapia,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    therapy_type = models.CharField(
        max_length=20,
        choices=[('individual', 'Individual'), ('couple', 'Pareja'), ('family', 'Familiar')],
        default='individual'
    )
    scores = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'terapia', 'therapy_type')
        verbose_name = "Perfil Emocional"
        verbose_name_plural = "Perfiles Emocionales"

    def __str__(self):
        return f"Perfil para {self.user.email} ({self.therapy_type})"
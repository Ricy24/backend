from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import date
from api.models import Terapia

class Mood(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mood = models.CharField(max_length=50)
    timestamp = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.user} - {self.mood} ({self.timestamp})"

    class Meta:
        indexes = [
            models.Index(fields=['user', 'timestamp']),  # Índice para consultas ordenadas por usuario y fecha
        ]

class SupportGroup(models.Model):
    name = models.CharField(max_length=100)
    time = models.DateTimeField()
    duration = models.CharField(max_length=10, default='1h')
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='support_groups')

    def __str__(self):
        return self.name

class PsychologicalTest(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    score = models.IntegerField()
    completed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.name} ({self.score})"

    class Meta:
        indexes = [
            models.Index(fields=['user', 'completed_at']),  # Índice para consultas por usuario y fecha
        ]

class DiaryEntry(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # --- NUEVO CAMPO ---
    terapia = models.ForeignKey(
        Terapia,
        on_delete=models.CASCADE,
        related_name='diary_entries',
        null=True, # Puede ser null si permites diarios fuera de terapia
        blank=True # O null=False, blank=False si *siempre* debe estar en una terapia
    )
    # --- FIN NUEVO CAMPO ---
    date = models.DateField(default=date.today)
    day_name = models.CharField(max_length=20)
    title = models.CharField(max_length=200, blank=True, null=True)
    content = models.TextField(blank=True)
    is_empty = models.BooleanField(default=False)
    emotion = models.CharField(
        max_length=20,
        choices=[
            # ... (tus choices) ...
             ('alegre', 'Día alegre'),
             ('triste', 'Día triste'),
             ('productivo', 'Día productivo'),
             ('estresante', 'Día estresante'),
             ('gratitud', 'Día de gratitud'),
             ('caotico', 'Día caótico'),
             ('relajante', 'Día relajante'),
             ('emocionante', 'Día emocionante'),
             ('reflexion', 'Día de reflexión'),
             ('vacio', 'Día vacío'),
        ],
        blank=True,
        null=True
    )

    def __str__(self):
        terapia_info = f" (Terapia: {self.terapia.id})" if self.terapia else ""
        return f"{self.user} - {self.date}{terapia_info} - {self.title or 'Sin título'}"

    class Meta:
        unique_together = ('user', 'terapia', 'date') # Asegura una entrada por día por terapia
        indexes = [
            models.Index(fields=['user', 'terapia', 'date']), # Índice optimizado
            models.Index(fields=['user', 'date']), # Mantenemos el original por si acaso
        ]

class DiaryConversation(models.Model):
    diary_entry = models.ForeignKey(DiaryEntry, on_delete=models.CASCADE, related_name='conversations')
    role = models.CharField(max_length=10, choices=[('user', 'User'), ('assistant', 'Assistant')])
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.role} - {self.diary_entry} ({self.timestamp})"

    class Meta:
        indexes = [
            models.Index(fields=['diary_entry', 'timestamp']),  # Índice para consultas por entrada y fecha
        ]

class UserStreak(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    current_streak = models.IntegerField(default=0)
    last_entry_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.user} - Racha: {self.current_streak}"

    class Meta:
        indexes = [
            models.Index(fields=['user']),  # Índice para consultas por usuario
        ]

class SleepLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    hours_slept = models.FloatField()  # Horas dormidas (puede ser decimal, ej. 7.5)
    date = models.DateField()  # Fecha del sueño
    sleep_quality = models.CharField(max_length=20, default='Intermedio')  # Nuevo campo
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'date')  # Solo un registro por usuario por día
        indexes = [
            models.Index(fields=['user', 'date']),  # Índice para consultas por usuario y fecha
        ]

    def __str__(self):
        return f"{self.user} - {self.hours_slept} horas ({self.date}) - {self.sleep_quality}"
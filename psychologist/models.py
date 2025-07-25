# psychologist/models.py
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from api.models import Usuario

class Specialty(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True,
        choices=[
            ('Ansiedad', 'Ansiedad'),
            ('Depresión', 'Depresión'),
            ('Terapia de pareja', 'Terapia de pareja'),
            ('Terapia familiar', 'Terapia familiar'),
            ('Trauma', 'Trauma'),
            ('Autoestima', 'Autoestima'),
            ('Adicciones', 'Adicciones'),
            ('Duelo', 'Duelo'),
            ('Estrés laboral', 'Estrés laboral'),
            ('Mindfulness', 'Mindfulness'),
        ]
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Especialidad"
        verbose_name_plural = "Especialidades"

class Language(models.Model):
    name = models.CharField(
        max_length=50,
        unique=True,
        choices=[
            ('Español', 'Español'),
            ('Inglés', 'Inglés'),
            ('Portugués', 'Portugués'),
            ('Francés', 'Francés'),
            ('Alemán', 'Alemán'),
        ]
    )

    def __str__(self):  # Corregido: añadido 'self'
        return self.name

    class Meta:
        verbose_name = "Idioma"
        verbose_name_plural = "Idiomas"

class Certification(models.Model):
    name = models.CharField(max_length=200)
    psychologist = models.ForeignKey(
        'PsychologistProfile',
        on_delete=models.CASCADE,
        related_name='certifications'
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Certificación"
        verbose_name_plural = "Certificaciones"

class PsychologistProfile(models.Model):
    user = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        related_name='psychologist_profile'
    )
    specialties = models.ManyToManyField(
        Specialty,
        blank=True,
        help_text="Selecciona las especialidades de la psicóloga"
    )
    bio = models.TextField(
        blank=True,
        null=True,
        max_length=500,
        help_text="Descripción corta de la psicóloga"
    )
    languages = models.ManyToManyField(
        Language,
        blank=True,
        help_text="Selecciona los idiomas que habla"
    )
    years_experience = models.PositiveIntegerField(
        default=0,
        blank=True,
        null=True,
        help_text="Años de experiencia profesional"
    )
    therapeutic_approach = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Enfoque terapéutico, ej. 'Cognitivo-conductual'"
    )

    offers_free_30min_session = models.BooleanField(
        default=False,
        help_text="Indica si la psicóloga ofrece una sesión gratuita de 30 minutos"
    )

    profile_visibility = models.BooleanField(
        default=True,
        verbose_name="Visibilidad del Perfil",
        help_text="Marca esta casilla si quieres que tu perfil aparezca en el listado público del marketplace."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Perfil de {self.user.nombre or self.user.email}"

    def clean(self):
        # Validaciones adicionales si es necesario
        pass

    class Meta:
        verbose_name = "Perfil de Psicóloga"
        verbose_name_plural = "Perfiles de Psicólogas"

class Availability(models.Model):
    psychologist = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='availability'
    )
    day_of_week = models.CharField(
        max_length=10,
        choices=[
            ('Monday', 'Lunes'),
            ('Tuesday', 'Martes'),
            ('Wednesday', 'Miércoles'),
            ('Thursday', 'Jueves'),
            ('Friday', 'Viernes'),
            ('Saturday', 'Sábado'),
            ('Sunday', 'Domingo'),
        ]
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.psychologist.nombre or self.psychologist.email} - {self.day_of_week} {self.start_time}-{self.end_time}"

def clean(self):
            # Validar que start_time < end_time
            if self.start_time and self.end_time and self.start_time >= self.end_time:
                raise ValidationError({"end_time": "La hora de fin debe ser posterior a la hora de inicio."}) # Error específico del campo

            # Validar solapamiento solo si tenemos todos los datos necesarios
            if self.psychologist and self.day_of_week and self.start_time and self.end_time:
                overlapping_query = Availability.objects.filter(
                    psychologist=self.psychologist,
                    day_of_week=self.day_of_week,
                    start_time__lt=self.end_time, # Solapa si empieza antes de que termine el nuevo
                    end_time__gt=self.start_time  # Solapa si termina después de que empiece el nuevo
                )
                # Si estamos actualizando (self.pk existe), excluimos el propio objeto
                if self.pk:
                    overlapping_query = overlapping_query.exclude(pk=self.pk)

                if overlapping_query.exists():
                    # Lanza un error que el serializer pueda entender (o un error general)
                    raise ValidationError(
                        "Este horario ({} {} - {}) se solapa con otro existente.".format(
                            self.get_day_of_week_display(), # Muestra nombre legible
                            self.start_time.strftime('%H:%M'),
                            self.end_time.strftime('%H:%M')
                        ),
                        code='overlap' # Código opcional
                    )

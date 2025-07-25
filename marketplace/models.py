# marketplace/models.py

from django.db import models
from psychologist.models import PsychologistProfile # Importamos el perfil

# Modelo para la formación académica
class Education(models.Model):
    psychologist_profile = models.ForeignKey(PsychologistProfile, on_delete=models.CASCADE, related_name='education')
    institution = models.CharField(max_length=255, verbose_name="Institución")
    degree = models.CharField(max_length=255, verbose_name="Título Obtenido")
    field_of_study = models.CharField(max_length=255, verbose_name="Campo de Estudio")
    start_year = models.PositiveIntegerField()
    end_year = models.PositiveIntegerField(null=True, blank=True, help_text="Dejar en blanco si aún está cursando")

    def __str__(self):
        return f"{self.degree} en {self.institution}"

    class Meta:
        verbose_name = "Formación Académica"
        verbose_name_plural = "Formaciones Académicas"
        ordering = ['-end_year', '-start_year']


# Modelo para las recomendaciones (libros, playlists, etc.)
class Recommendation(models.Model):
    RECOMMENDATION_TYPES = [
        ('book', 'Libro'),
        ('playlist', 'Playlist'),
        ('video', 'Video'),
        ('podcast', 'Podcast'),
        ('article', 'Artículo'),
    ]
    psychologist_profile = models.ForeignKey(PsychologistProfile, on_delete=models.CASCADE, related_name='recommendations')
    title = models.CharField(max_length=255, verbose_name="Título")
    type = models.CharField(max_length=20, choices=RECOMMENDATION_TYPES, verbose_name="Tipo")
    link = models.URLField(max_length=500, verbose_name="Enlace")
    description = models.TextField(blank=True, verbose_name="Descripción breve")
    cover_image = models.ImageField(upload_to='recommendations/covers/', null=True, blank=True, verbose_name="Imagen de portada")

    def __str__(self):
        return f"{self.get_type_display()}: {self.title}"
    
    class Meta:
        verbose_name = "Recomendación"
        verbose_name_plural = "Recomendaciones"

# Modelo para el blog/artículos de cada psicólogo
class BlogPost(models.Model):
    psychologist_profile = models.ForeignKey(PsychologistProfile, on_delete=models.CASCADE, related_name='blog_posts')
    title = models.CharField(max_length=255, verbose_name="Título del Artículo")
    content = models.TextField(verbose_name="Contenido")
    header_image = models.ImageField(upload_to='blog_posts/headers/', null=True, blank=True, verbose_name="Imagen de cabecera")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True, help_text="Dejar en blanco para guardar como borrador")
    
    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "Artículo de Blog"
        verbose_name_plural = "Artículos de Blog"
        ordering = ['-published_at', '-created_at']
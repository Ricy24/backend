# landing_api/models.py
from django.db import models
from django.utils import timezone

class Comment(models.Model):
    # Identificador del post/página de Astro al que pertenece el comentario
    # Puede ser un slug, un ID único que uses en Astro, etc.
    post_identifier = models.CharField(max_length=255, db_index=True)
    author_name = models.CharField(max_length=100)
    author_email = models.EmailField(blank=True, null=True) # Opcional
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    approved = models.BooleanField(default=False) # Para moderación

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Comment by {self.author_name} on {self.post_identifier}"

class NewsletterSubscription(models.Model):
    email = models.EmailField(unique=True)
    subscribed_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.email
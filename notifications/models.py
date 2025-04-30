from django.db import models
from django.utils import timezone
from api.models import Usuario

class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('message', 'Nuevo mensaje'),
        ('meeting', 'Próxima reunión'),
        ('like', 'Me gusta en tu post'),
        ('comment', 'Comentario en tu post'),
    )

    recipient = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    message = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)
    related_object_id = models.CharField(max_length=100, null=True, blank=True)  # ID del mensaje, evento o post

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient} - {self.notification_type} - {self.message}"
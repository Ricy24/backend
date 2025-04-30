from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from api.models import Usuario

class UserProfile(models.Model):
    user = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='profile')
    public_likes = models.BooleanField(default=False, help_text='Si es True, los likes del usuario serán visibles en su perfil público')
    
    def __str__(self):
        return f"Perfil de {self.user.email}"

# Señal para crear automáticamente un perfil cuando se crea un usuario
@receiver(post_save, sender=Usuario)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=Usuario)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        UserProfile.objects.create(user=instance)
    instance.profile.save()

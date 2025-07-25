# api/models.py
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

# Manager personalizado
class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('El campo email es obligatorio')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser debe tener is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser debe tener is_superuser=True.')
        return self.create_user(email, password, **extra_fields)

# Función para definir la ruta de subida de las fotos de perfil
def user_profile_pic_path(instance, filename):
    # El archivo se subirá a MEDIA_ROOT/profile_pics/user_{id}/{filename}
    # Asegúrate que el ID exista al guardar (puede requerir guardar primero sin foto y luego actualizar)
    # O usar un UUID temporal si prefieres no depender del ID inmediato.
    # Por simplicidad, usaremos el ID, asumiendo que se guarda tras la creación inicial.
    # OJO: Si el usuario se crea y la foto se añade en la misma transacción, el ID podría no estar disponible.
    # Una alternativa es guardar en una ruta temporal o usar email/uuid.
    # Vamos a usar email por ahora, que es único y conocido al crear.
    email_prefix = instance.email.split('@')[0]
    return f'profile_pics/user_{email_prefix}/{filename}'

class Usuario(AbstractUser):
    GENDER_CHOICES = [
        ('male', 'Masculino'),
        ('female', 'Femenino'),
        ('other', 'Otro'),
        ('prefer_not_to_say', 'Prefiero no decirlo'),
    ]
    is_psychologist = models.BooleanField(default=False)
    # uid ya no parece necesario si usas el ID por defecto de Django. Considera eliminarlo.
    # uid = models.CharField(max_length=255, unique=True, blank=True, null=True)
    birthdate = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=2, blank=True, null=True)
    nombre = models.CharField(max_length=255, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    tipo_cuenta = models.CharField(max_length=50, default="Free")
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=False)
    ultima_sesion = models.DateTimeField(default=timezone.now)
    email = models.EmailField(unique=True)
    sesiones_completadas = models.IntegerField(default=0)
    is_new_user = models.BooleanField(default=True)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True, null=True)
    reset_token = models.CharField(max_length=36, null=True, blank=True)
    reset_token_expiry = models.DateTimeField(null=True, blank=True)

    # --- NUEVO CAMPO ---
    profile_pic = models.ImageField(
        upload_to=user_profile_pic_path, # Función para determinar la ruta
        null=True,                       # Opcional en DB
        blank=True,                      # Opcional en formularios/admin
        verbose_name="Foto de perfil"
    )
    # --- FIN NUEVO CAMPO ---

    username = None
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = [] # Nombre ya no es requerido aquí si lo pides en el serializer
    objects = CustomUserManager() # Asegúrate que tu manager esté correctamente asignado

    def __str__(self):
        return self.email

    @property
    def dias_activos(self):
        today = timezone.now()
        # Asegurarse que fecha_registro no sea None (aunque auto_now_add debería prevenirlo)
        if self.fecha_registro:
            diff = today - self.fecha_registro
            return diff.days
        return 0

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    # Sobrescribir save si necesitas lógica extra al guardar profile_pic
    # def save(self, *args, **kwargs):
    #     # Lógica antes de guardar...
    #     super().save(*args, **kwargs)
    #     # Lógica después de guardar...
    
# Modelo Terapia
# api/models.py
class Terapia(models.Model):
    TIPO_CHOICES = [
        ('individual', 'Individual'),
    ]
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='individual')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    herramientas = models.JSONField(default=dict, blank=True)
    event = models.ForeignKey('google_calendar.CalendarEvent', on_delete=models.CASCADE, related_name='terapias', null=True, blank=True)

    @property
    def limite_miembros(self):
        return 1

    def __str__(self):
        return f"Terapia {self.tipo} - {self.id}"
    
# Modelo MiembroTerapia
class MiembroTerapia(models.Model):
    usuario = models.ForeignKey('Usuario', on_delete=models.CASCADE)
    terapia = models.ForeignKey(Terapia, on_delete=models.CASCADE)
    fecha_union = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('usuario', 'terapia')

    def __str__(self):
        return f"{self.usuario.email} en {self.terapia}"

# Modelo InvitacionTerapia
class InvitacionTerapia(models.Model):
    terapia = models.ForeignKey(Terapia, on_delete=models.CASCADE)
    token = models.CharField(max_length=255, unique=True)
    creado_por = models.ForeignKey('Usuario', on_delete=models.CASCADE)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    usado = models.BooleanField(default=False)

    def __str__(self):
        return f"Invitación para {self.terapia} - {self.token}"

# Otros modelos (InitialAssessment, WellnessGoal, Resource)
class InitialAssessment(models.Model):
    user = models.ForeignKey('Usuario', on_delete=models.CASCADE)
    completed = models.BooleanField(default=False)
    responses = models.JSONField()
    diagnosis = models.TextField(blank=True)
    therapy_recommendations = models.TextField(blank=True)
    sessions_needed = models.IntegerField(default=0)
    therapy_type = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - Assessment ({'Completed' if self.completed else 'Pending'})"

class WellnessGoal(models.Model):
    user = models.ForeignKey('Usuario', on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    progress = models.IntegerField(default=0)
    color = models.CharField(max_length=50, default='from-indigo-500-to-purple-600')
    icon = models.CharField(max_length=50, default='Target')
    is_auto_generated = models.BooleanField(default=False)
    therapy_related = models.BooleanField(default=False)
    target_progress = models.IntegerField(default=100)

    def __str__(self):
        return f"{self.user} - {self.title} ({self.progress}%)"

class Resource(models.Model):
    RESOURCE_TYPES = [
        ('article', 'Artículo'),
        ('song', 'Canción'),
        ('book', 'Libro'),
        ('video', 'Video'),
        ('exercise', 'Ejercicio'),
        ('tip', 'Consejo'),
    ]
    title = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=RESOURCE_TYPES)
    content = models.TextField()
    diagnosis = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.type})"
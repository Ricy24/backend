# backend/celery.py
import os
from celery import Celery
from celery.schedules import crontab

# Establecer la variable de entorno por defecto de Django para el programa 'celery'.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings') # Asegúrate que 'backend' sea el nombre correcto de tu directorio de proyecto

app = Celery('backend') # Define la instancia de Celery UNA SOLA VEZ

# Usar una cadena aquí significa que el worker no tendrá que serializar
# el objeto de configuración al hijo.
# Namespace='CELERY' significa que todas las claves de configuración de Celery
# deben tener un prefijo `CELERY_`.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Cargar módulos de tareas de todas las apps Django registradas.
# Esto es crucial para que Celery encuentre tus tareas en google_calendar/tasks.py, etc.
app.autodiscover_tasks()

# Configuración de Celery Beat (tareas periódicas)
# Esto debe ir DESPUÉS de que 'app' esté completamente configurada.
app.conf.beat_schedule = {
    'assign-daily-challenges': {
        'task': 'therapy.tasks.assign_daily_challenges', # Tarea de tu app 'therapy'
        'schedule': crontab(hour=0, minute=0),  # A medianoche
    },
    # Si tienes otras tareas periódicas, añádelas aquí.
    # Las tareas programadas con 'eta' (como tus recordatorios de WhatsApp)
    # NO necesitan estar en beat_schedule. Se programan dinámicamente.
}

# Opcional: Una tarea de depuración para verificar que Celery funciona
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
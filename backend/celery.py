import os
from celery import Celery
from celery.schedules import crontab


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

app = Celery('backend')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


app = Celery('backend')
app.conf.beat_schedule = {
    'assign-daily-challenges': {
        'task': 'therapy.tasks.assign_daily_challenges',
        'schedule': crontab(hour=0, minute=0),  # A medianoche
    },
}
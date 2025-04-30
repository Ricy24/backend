from celery import shared_task
from django.utils import timezone
from google_calendar.models import CalendarEvent
from api.models import MiembroTerapia
from notifications.models import Notification
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

@shared_task
def check_upcoming_meetings():
    now = timezone.now()
    ten_minutes_later = now + timezone.timedelta(minutes=10)
    events = CalendarEvent.objects.filter(
        start_time__gte=now,
        start_time__lte=ten_minutes_later,
        type='therapy'
    )

    channel_layer = get_channel_layer()
    for event in events:
        if event.terapia:
            miembros = MiembroTerapia.objects.filter(terapia=event.terapia)
            for miembro in miembros:
                Notification.objects.create(
                    recipient=miembro.usuario,
                    notification_type='meeting',
                    message=f"Tu reunión '{event.title}' comienza en menos de 10 minutos",
                    related_object_id=event.event_id
                )
                async_to_sync(channel_layer.group_send)(
                    f"user_{miembro.usuario.id}",
                    {
                        'type': 'send_notification',
                        'notification_type': 'meeting',
                        'message': f"Tu reunión '{event.title}' comienza en menos de 10 minutos",
                        'created_at': timezone.now().isoformat(),
                        'related_object_id': event.event_id,
                    }
                )
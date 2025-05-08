# google_calendar/tasks.py

from celery import shared_task
from django.utils import timezone
from django.conf import settings
from .models import CalendarEvent # Correcto si tasks.py está en la misma app que models.py
from whatsapp.services import send_whatsapp_message # Ajusta si es necesario
from datetime import timedelta # Añadir esta importación si no está
import logging

logger = logging.getLogger(__name__)

REMINDER_MINUTES_BEFORE_TASK = getattr(settings, 'REMINDER_MINUTES_BEFORE_TASK', 5) # Puedes definirla en settings

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_session_reminder_whatsapp_task(self, event_id, recipient_phone, recipient_name, recipient_role, other_party_name):
    """
    Envía un recordatorio de WhatsApp para una sesión.
    Args:
        event_id: ID del CalendarEvent.
        recipient_phone: Teléfono del destinatario.
        recipient_name: Nombre del destinatario.
        recipient_role: 'patient' o 'psychologist'.
        other_party_name: Nombre de la otra persona en la sesión.
    """
    try:
        event = CalendarEvent.objects.get(id=event_id) # Usar el ID numérico del evento
    except CalendarEvent.DoesNotExist:
        logger.warning(f"Task: Evento con ID {event_id} no encontrado. No se enviará recordatorio a {recipient_phone}.")
        return f"Evento ID {event_id} no encontrado."
    except Exception as e:
        logger.error(f"Task: Error buscando evento ID {event_id}: {e}. Reintentando...")
        raise self.retry(exc=e)

    # Verificar si el evento aún es válido (ej. no cancelado)
    # if hasattr(event, 'status') and event.status == 'cancelled':
    #     logger.info(f"Task: Evento ID {event_id} está cancelado. No se enviará recordatorio a {recipient_phone}.")
    #     return f"Evento ID {event_id} cancelado."

    now = timezone.now()
    # El ETA ya manejó el momento, pero una verificación adicional no daña
    # Podrías ajustar la ventana si lo deseas.
    if not (event.start_time - timedelta(minutes=REMINDER_MINUTES_BEFORE_TASK + 10) <= now <= event.start_time + timedelta(minutes=10) ): # Una ventana un poco más amplia para la tarea
        logger.info(f"Task: Evento ID {event_id} ({event.start_time.isoformat()}) fuera de la ventana de recordatorio ({now.isoformat()}). No se enviará a {recipient_phone}.")
        return f"Evento ID {event_id} fuera de ventana de recordatorio."

    jitsi_link = event.jitsi_meet_link
    if not jitsi_link:
        jitsi_link = event.generate_jitsi_meet_link() # Asume que este método guarda y retorna el link
        if not jitsi_link:
            logger.error(f"Task: No se pudo generar/obtener el enlace Jitsi para el evento ID {event_id} (Dest: {recipient_phone}). No se enviará recordatorio.")
            return f"No se pudo obtener Jitsi link para evento ID {event_id}."

    session_time_local = event.start_time.astimezone(timezone.get_current_timezone())
    formatted_time = session_time_local.strftime("%I:%M %p %Z")

    if recipient_role == "patient":
        reminder_message = f"""¡Hola {recipient_name}! 👋
Tu sesión de terapia con la psicóloga {other_party_name} está por comenzar a las {formatted_time}.

🔗 Únete aquí: {jitsi_link}

Por favor, sé puntual. ¡Te esperamos en Senti!"""
    elif recipient_role == "psychologist":
        reminder_message = f"""¡Hola Psic. {recipient_name}! 🔔
Tu sesión de terapia con el paciente {other_party_name} comienza en breve a las {formatted_time}.

🔗 Enlace (para tu referencia, el paciente ya lo recibió): {jitsi_link}

Prepárate para la sesión.
Plataforma Senti."""
    else:
        logger.error(f"Task: Rol de destinatario desconocido '{recipient_role}' para evento ID {event_id}.")
        return f"Rol desconocido {recipient_role}"

    try:
        wa_success, wa_response = send_whatsapp_message(recipient_phone, reminder_message)
        if wa_success:
            logger.info(f"Task: Recordatorio de WhatsApp enviado exitosamente a {recipient_phone} para evento ID {event_id}.")
            return f"Éxito: {wa_response}"
        else:
            logger.error(f"Task: Error enviando recordatorio de WhatsApp a {recipient_phone} para evento ID {event_id}: {wa_response}.")
            raise Exception(f"Fallo al enviar WhatsApp: {wa_response}") # Activa reintento de Celery

    except Exception as e_send:
        logger.error(f"Task: Excepción al enviar WhatsApp para evento ID {event_id} a {recipient_phone}: {e_send}", exc_info=True)
        raise self.retry(exc=e_send, countdown=60 * (self.request.retries + 1))
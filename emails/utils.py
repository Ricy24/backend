
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

import logging # Para registrar éxitos y errores

logger = logging.getLogger(__name__)

def send_brevo_email(subject, to_email, template_name, context):
    """
    Envía un correo HTML usando el backend SMTP configurado en settings.py (Zoho).
    NOTA: El nombre de la función se mantiene como 'send_brevo_email' por
    compatibilidad con el código existente, pero ya NO usa la API de Brevo.

    :param subject: Asunto del correo
    :param to_email: Correo del destinatario (string)
    :param template_name: Nombre del template HTML relativo a la carpeta de templates
                          (ej: 'emails/welcome_email.html')
    :param context: Diccionario con variables para el template
    :return: True si el correo se envió con éxito, False en caso contrario.
    """
    logger.debug(f"Intentando enviar correo via Django SMTP (Zoho) a: {to_email}, Asunto: {subject}")

    try:
        # 1. Renderizar el template HTML con el contexto proporcionado
        #    Asegúrate que la ruta del template es correcta. Si tus templates
        #    están en 'templates/emails/', la ruta sería 'emails/nombre_template.html'.
        #    Si están directamente en 'emails/templates/', sería solo 'nombre_template.html'.
        #    Ajusta el prefijo 'emails/' si es necesario según tu estructura.
        try:
            html_content = render_to_string(f'emails/{template_name}', context)
        except Exception as render_error:
            logger.error(f"Error renderizando template '{template_name}' para {to_email}: {render_error}", exc_info=True)
            return False # No se puede enviar si el template falla

        # 2. Obtener el remitente desde la configuración de Django
        #    Usará el DEFAULT_FROM_EMAIL = "SentiBien <no-reply@senti.lat>"
        from_email = settings.DEFAULT_FROM_EMAIL

        # 3. Crear el objeto EmailMessage
        #    Pasamos el contenido HTML como cuerpo principal.
        email = EmailMessage(
            subject=subject,          # Asunto
            body=html_content,        # Cuerpo del mensaje (HTML)
            from_email=from_email,    # Remitente (desde settings)
            to=[to_email],            # Destinatario(s) - debe ser una lista o tupla
            # Opcional: puedes añadir Bcc o Cc aquí si lo necesitas:
            # bcc=['copiaoculta@ejemplo.com'],
            # cc=['copiavisible@ejemplo.com'],
        )

        # 4. Indicar explícitamente que el contenido es HTML
        email.content_subtype = "html"

        # 5. Enviar el correo usando el backend configurado en settings.py (Zoho)
        email.send()

        # 6. Registrar éxito
        logger.info(f"Correo enviado exitosamente a {to_email} usando Django SMTP (Zoho). Asunto: {subject}")
        return True

    except Exception as e:
        # 7. Capturar cualquier excepción durante el proceso de envío
        #    (Error de autenticación, conexión, configuración, etc.)
        logger.error(f"Error al enviar correo (Django SMTP/Zoho) a {to_email}. Asunto: {subject}. Error: {e}", exc_info=True)
        return False
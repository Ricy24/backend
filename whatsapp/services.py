import requests
from django.conf import settings
import logging

# Configura el logger para obtener información útil en la consola o en archivos de log
logger = logging.getLogger(__name__)

def send_whatsapp_message(
    phone_number: str,
    message_type: str = "text",
    message_text: str = None,
    content_data: dict = None,
    message_text_fallback: str = "Mensaje de WhatsApp"
) -> tuple[bool, str]:
    """
    Envía un mensaje de WhatsApp a través de un servicio externo (ej. Baileys).
    Esta función es flexible y puede manejar diferentes tipos de mensajes
    basado en el parámetro 'message_type'.

    Args:
        phone_number (str): Número de teléfono destino (ej: "573001234567").
        message_type (str): El tipo de mensaje a enviar. Puede ser 'text' para
                            mensajes simples o 'buttons' para mensajes con botones.
                            Por defecto es 'text'.
        message_text (str, optional): El contenido del mensaje si message_type es 'text'.
        content_data (dict, optional): La estructura completa del mensaje si es un tipo
                                       complejo como 'buttons'. Por ejemplo:
                                       {'text': 'Hola', 'buttons': [...], 'footer': '...'}
        message_text_fallback (str): Un texto descriptivo que se usará en los logs
                                     para identificar la acción.

    Returns:
        tuple[bool, str]: Una tupla que contiene:
                          - Un booleano indicando si el envío fue exitoso.
                          - Un string con el mensaje de respuesta o el detalle del error.
    """
    baileys_url = settings.BAILEYS_SERVICE_URL
    api_key = settings.BAILEYS_API_KEY

    # Verificación de configuración esencial
    if not baileys_url or not api_key:
        error_msg = "BAILEYS_SERVICE_URL o BAILEYS_API_KEY no están configuradas en settings.py."
        logger.error(error_msg)
        return False, "Configuración del servicio Baileys incompleta en Django."

    # --- Construcción dinámica del payload ---
    payload = {"to": phone_number}

    if message_type == "text" and message_text:
        # Para mensajes de texto simples
        payload["message"] = message_text
    elif message_type == "buttons" and content_data:
        # Para mensajes con botones, asumimos que content_data contiene
        # toda la estructura necesaria (texto, botones, footer, etc.)
        # y la fusionamos con el payload.
        # ¡IMPORTANTE! Asegúrate que esta estructura coincida con lo que
        # tu servicio Baileys espera.
        # Por ejemplo, si Baileys espera { "to": ..., "message": { "text": ... } },
        # esta parte necesitaría ajustarse.
        payload.update(content_data)
    else:
        # Si la llamada es incorrecta (ej. tipo 'text' sin 'message_text')
        error_msg = f"Llamada inválida a send_whatsapp_message para {phone_number}: Faltan parámetros para el tipo '{message_type}'."
        logger.error(error_msg)
        return False, "Parámetros de mensaje inválidos."

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key
    }

    logger.info(f"Intentando enviar WhatsApp ({message_text_fallback}) a {phone_number} via {baileys_url}")
    logger.debug(f"Payload a enviar: {payload}") # Log de debug para ver qué se envía exactamente

    try:
        response = requests.post(baileys_url, json=payload, headers=headers, timeout=20)
        response.raise_for_status()  # Lanza una excepción para respuestas de error (4xx o 5xx)

        response_data = response.json()
        if response_data.get("success"):
            success_msg = response_data.get('message', 'Éxito sin mensaje detallado.')
            logger.info(f"Mensaje de WhatsApp enviado exitosamente a {phone_number}. Respuesta: {success_msg}")
            return True, success_msg
        else:
            error_msg = response_data.get('error', 'Error desconocido del servicio Baileys')
            logger.error(f"Error reportado por el servicio Baileys al enviar a {phone_number}: {error_msg}")
            return False, error_msg

    except requests.exceptions.HTTPError as errh:
        error_detail = f"Error HTTP {errh.response.status_code}"
        try:
            # Intenta obtener más detalles del cuerpo de la respuesta si es JSON
            error_detail += f" - {errh.response.json().get('error', errh.response.text)}"
        except requests.exceptions.JSONDecodeError:
            error_detail += f" - {errh.response.text}"
        logger.error(f"Error HTTP al contactar servicio Baileys para {phone_number}: {error_detail}")
        return False, error_detail
    except requests.exceptions.ConnectionError as errc:
        logger.error(f"Error de conexión al servicio Baileys ({baileys_url}) para {phone_number}: {errc}")
        return False, "Error de Conexión al servicio Baileys. ¿Está el servicio corriendo?"
    except requests.exceptions.Timeout:
        logger.error(f"Timeout al contactar servicio Baileys para {phone_number}.")
        return False, "Timeout contactando al servicio Baileys."
    except requests.exceptions.RequestException as err:
        logger.error(f"Error general de requests al contactar servicio Baileys para {phone_number}: {err}")
        return False, "Error general de Request al servicio Baileys."
    except Exception as e:
        logger.error(f"Excepción inesperada al intentar enviar WhatsApp a {phone_number}: {e}", exc_info=True)
        return False, f"Excepción inesperada: {str(e)}"
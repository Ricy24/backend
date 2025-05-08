import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_whatsapp_message(phone_number: str, message_text: str) -> tuple[bool, str]:
    """
    Envía un mensaje de WhatsApp a través del servicio Baileys.

    Args:
        phone_number (str): Número de teléfono destino (ej: "521XXXXXXXXXX").
        message_text (str): El mensaje a enviar.

    Returns:
        tuple[bool, str]: (True/False indicando éxito, mensaje de respuesta/error).
    """
    baileys_url = settings.BAILEYS_SERVICE_URL
    api_key = settings.BAILEYS_API_KEY

    if not baileys_url or not api_key:
        logger.error("BAILEYS_SERVICE_URL o BAILEYS_API_KEY no están configuradas en settings.py.")
        return False, "Configuración del servicio Baileys incompleta en Django."

    payload = {
        "to": phone_number,
        "message": message_text
    }
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key
    }

    logger.info(f"Intentando enviar WhatsApp a {phone_number} via {baileys_url}")

    try:
        response = requests.post(baileys_url, json=payload, headers=headers, timeout=20)
        response.raise_for_status()

        response_data = response.json()
        if response_data.get("success"):
            logger.info(f"Mensaje de WhatsApp enviado exitosamente a {phone_number}. Respuesta: {response_data.get('message')}")
            return True, response_data.get('message', 'Éxito sin mensaje detallado.')
        else:
            error_msg = response_data.get('error', 'Error desconocido del servicio Baileys')
            logger.error(f"Error reportado por el servicio Baileys al enviar a {phone_number}: {error_msg}")
            return False, error_msg

    except requests.exceptions.HTTPError as errh:
        error_detail = f"Error HTTP {errh.response.status_code}"
        try: # Intenta obtener más detalles del cuerpo de la respuesta si es JSON
            error_detail += f" - {errh.response.json().get('error', errh.response.text)}"
        except requests.exceptions.JSONDecodeError:
            error_detail += f" - {errh.response.text}"
        logger.error(f"Error HTTP al contactar servicio Baileys para {phone_number}: {error_detail}")
        return False, error_detail
    except requests.exceptions.ConnectionError as errc:
        logger.error(f"Error de conexión al servicio Baileys ({baileys_url}) para {phone_number}: {errc}")
        return False, "Error de Conexión al servicio Baileys. ¿Está el servicio Baileys corriendo?"
    except requests.exceptions.Timeout:
        logger.error(f"Timeout al contactar servicio Baileys para {phone_number}.")
        return False, "Timeout contactando al servicio Baileys."
    except requests.exceptions.RequestException as err:
        logger.error(f"Error general de requests al contactar servicio Baileys para {phone_number}: {err}")
        return False, "Error general de Request al servicio Baileys."
    except Exception as e:
        logger.error(f"Excepción inesperada al intentar enviar WhatsApp a {phone_number}: {e}", exc_info=True)
        return False, f"Excepción inesperada: {str(e)}"
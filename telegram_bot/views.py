# telegram_bot/views.py

import json
import logging
from datetime import datetime

import requests # Necesitarás instalarlo: pip install requests
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils.timezone import make_aware

# Asegúrate de que tus modelos estén correctamente importados
try:
    from .models import TelegramChat, TelegramMessage
except ImportError: # Manejo por si los modelos aún no existen durante alguna fase de desarrollo inicial
    TelegramChat = None
    TelegramMessage = None
    logging.warning("Modelos TelegramChat o TelegramMessage no encontrados al importar en views.py. Asegúrate de que existan y las migraciones estén aplicadas.")


# from api.models import Usuario # Importa tu modelo de usuario si lo necesitas para vincular

logger = logging.getLogger(__name__)

# --- Funciones de utilidad para enviar mensajes (podrían ir en utils.py) ---
def send_telegram_message(chat_id, text, parse_mode=None, reply_markup=None):
    """Envía un mensaje a un chat de Telegram."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN no está configurado.")
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()  # Lanza HTTPError para malas respuestas (4XX o 5XX)
        # No imprimir toda la respuesta json() si contiene el token o datos sensibles
        logger.info(f"Mensaje enviado a {chat_id}. Status: {response.status_code}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error enviando mensaje a {chat_id}: {e}")
        # Podrías también loggear response.text si está disponible para más detalles del error de la API de Telegram
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Respuesta de Telegram (error): {e.response.text}")
        return False
# --- Fin funciones de utilidad ---


@method_decorator(csrf_exempt, name='dispatch')
class TelegramWebhookView(View):
    # webhook_secret ya no se pasa como argumento desde la URL
    def post(self, request): # <--- CAMBIO AQUÍ: webhook_secret eliminado de los parámetros
        # La verificación del secreto que estaba aquí fue eliminada.
        # Se asume que la URL completa (incluyendo el secreto en el path)
        # ya proporciona suficiente seguridad para este endpoint.
        # Considera añadir una verificación si necesitas una capa extra,
        # por ejemplo, comprobando una cabecera personalizada o parte del request.path.

        # logger.info(f"Webhook POST request recibido en path: {request.path}") # Para depurar el path

        try:
            data = json.loads(request.body.decode('utf-8'))
            logger.debug(f"Webhook recibido (raw data): {data}")
        except json.JSONDecodeError:
            logger.error("Error decodificando JSON del webhook.")
            return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

        # Guarda la actualización completa para depuración si es necesario
        # TelegramUpdateLog.objects.create(payload=data) # Si tienes un modelo para esto

        if 'message' in data:
            self.handle_message(data['message'], raw_update=data)
        elif 'callback_query' in data:
            self.handle_callback_query(data['callback_query'], raw_update=data)
        # Puedes añadir más manejadores para 'edited_message', 'channel_post', etc.
        else:
            logger.warning(f"Tipo de actualización no manejada recibida: {list(data.keys())}")
            # Es buena idea responder ok incluso si no manejas el tipo, para que Telegram no reintente.
            return JsonResponse({"status": "ok", "message": "Update type not handled but acknowledged"})


        return JsonResponse({"status": "ok"}) # Telegram espera un 200 OK

    def handle_message(self, message_data, raw_update):
        # Verifica que los modelos estén disponibles
        if not TelegramChat or not TelegramMessage:
            logger.error("Modelos de Telegram no están disponibles en handle_message. Saltando procesamiento.")
            return

        message_id = message_data['message_id']
        chat_data = message_data['chat']
        chat_id = chat_data['id']
        text = message_data.get('text') # .get() es más seguro que acceso directo por si no hay 'text'
        message_date_timestamp = message_data.get('date')

        if message_date_timestamp:
            message_date = make_aware(datetime.fromtimestamp(message_date_timestamp))
        else:
            logger.warning(f"Mensaje {message_id} no tiene campo 'date'. Usando now().")
            message_date = make_aware(datetime.now())


        from_user_data = message_data.get('from', {})
        from_user_id = from_user_data.get('id')

        # Crear o actualizar el chat
        chat, created_chat = TelegramChat.objects.update_or_create(
            chat_id=chat_id,
            defaults={
                'type': chat_data.get('type', 'private'),
                'first_name': chat_data.get('first_name'),
                'last_name': chat_data.get('last_name'),
                'username': chat_data.get('username'),
                # 'is_active_support': True, # Podrías querer poner esto por defecto o manejarlo
            }
        )
        if created_chat:
            logger.info(f"Nuevo chat creado: {chat_id} (@{chat.username or chat.first_name or ''})")

        # Guardar el mensaje
        try:
            # Evitar duplicados si Telegram reenvía
            if not TelegramMessage.objects.filter(message_id=message_id).exists():
                TelegramMessage.objects.create(
                    message_id=message_id,
                    chat=chat,
                    from_user_id=from_user_id,
                    text=text,
                    date=message_date,
                    is_from_bot=False, # Este mensaje es del usuario
                    raw_update=raw_update
                )
                logger.info(f"Mensaje {message_id} de {chat_id} guardado.")
            else:
                logger.info(f"Mensaje {message_id} de {chat_id} ya existe, no se guarda de nuevo.")
                return # Importante: si ya existe, no procesar de nuevo la lógica de respuesta para evitar bucles o spam.

        except Exception as e:
            logger.error(f"No se pudo guardar el mensaje {message_id} para el chat {chat_id}: {e}")
            # Dependiendo del error, podrías querer no continuar.
            return


        # Lógica de respuesta básica
        if text: # Solo procesar si hay texto
            if text.lower().strip().startswith('/start'):
                welcome_message = f"¡Hola {chat.first_name or 'usuario'}! Bienvenido al soporte de Senti. ¿En qué podemos ayudarte?"
                send_telegram_message(chat_id, welcome_message)
            elif text.lower().strip().startswith('/help'):
                help_message = "Puedes escribir tu consulta y un agente se pondrá en contacto contigo.\nComandos disponibles:\n/start - Iniciar conversación\n/help - Mostrar esta ayuda"
                send_telegram_message(chat_id, help_message)
            else:
                # Lógica para soporte:
                received_message = "Hemos recibido tu mensaje. Un agente de Senti te contactará pronto."
                send_telegram_message(chat_id, received_message)

                # Ejemplo de notificación a un admin (si tienes TELEGRAM_ADMIN_CHAT_ID configurado)
                if settings.TELEGRAM_ADMIN_CHAT_ID and settings.TELEGRAM_ADMIN_CHAT_ID != chat_id:
                    # Asegurarse de que el texto no sea demasiado largo o contenga caracteres que rompan MarkdownV2
                    escaped_text = text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]') \
                                       .replace('(', '\\(').replace(')', '\\)').replace('~', '\\~').replace('`', '\\`') \
                                       .replace('>', '\\>').replace('#', '\\#').replace('+', '\\+').replace('-', '\\-') \
                                       .replace('=', '\\=').replace('|', '\\|').replace('{', '\\{').replace('}', '\\}') \
                                       .replace('.', '\\.').replace('!', '\\!')
                    
                    admin_message = (
                        f"Nuevo mensaje de soporte de @{chat.username or chat.first_name or chat_id} \\(ID: `{chat_id}`\\):\n"
                        f"```\n{escaped_text}\n```" # Usar texto escapado
                    )
                    send_telegram_message(settings.TELEGRAM_ADMIN_CHAT_ID, admin_message, parse_mode="MarkdownV2")
        else:
            logger.info(f"Mensaje de {chat_id} sin texto (ej. foto, sticker). No se envía respuesta automática.")


    def handle_callback_query(self, callback_query_data, raw_update):
        query_id = callback_query_data['id']
        from_user_data = callback_query_data.get('from', {}) # .get() para seguridad
        from_user_id = from_user_data.get('id')
        
        message_info = callback_query_data.get('message')
        chat_instance = None
        if message_info:
            chat_instance = message_info.get('chat')

        data_payload = callback_query_data.get('data')

        logger.info(f"Callback query recibido: id={query_id}, from_user_id={from_user_id}, data={data_payload}")

        # Siempre debes responder a un callback_query.
        ack_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
        try:
            requests.post(ack_url, json={'callback_query_id': query_id}, timeout=5)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error al acusar recibo del callback query {query_id}: {e}")

        # Aquí procesas `data_payload`
        if chat_instance and data_payload:
            chat_id = chat_instance.get('id')
            if not chat_id:
                logger.warning(f"Callback query {query_id} no tiene chat_id en message.chat.")
                return

            if data_payload == 'accion_ejemplo_1':
                send_telegram_message(chat_id, "Has pulsado el botón de ejemplo 1.")
            elif data_payload == 'accion_ejemplo_2':
                send_telegram_message(chat_id, "Pulsaste el botón de ejemplo 2.")
            else:
                send_telegram_message(chat_id, f"Callback recibido con datos: {data_payload}")
        else:
            logger.warning(f"Callback query {query_id} sin chat_instance o data_payload. No se procesa acción.")
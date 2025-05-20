import json
import logging
from datetime import datetime

import requests
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils.timezone import make_aware

# Importar la librería de Groq
from groq import Groq

# Asegúrate de que tus modelos estén correctamente importados
try:
    from .models import TelegramChat, TelegramMessage
    # from .models import KnowledgeItem # Si planeas usar RAG o una base de conocimiento
except ImportError:
    TelegramChat = None
    TelegramMessage = None
    # KnowledgeItem = None
    logging.warning("Modelos no encontrados al importar en views.py.")

logger = logging.getLogger(__name__)

# --- Funciones de utilidad para enviar mensajes (sin cambios) ---
def send_telegram_message(chat_id, text, parse_mode=None, reply_markup=None):
    # ... (código existente) ...
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
        response.raise_for_status()
        logger.info(f"Mensaje enviado a {chat_id}. Status: {response.status_code}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error enviando mensaje a {chat_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Respuesta de Telegram (error): {e.response.text}")
        return False
# --- Fin funciones de utilidad ---

# --- Función para obtener respuesta de Groq ---
def get_groq_response(user_query, chat_history=None):
    """
    Obtiene una respuesta del modelo de lenguaje usando la API de Groq.
    """
    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY no está configurada en settings.")
        return "Lo siento, no puedo procesar tu solicitud en este momento (error de configuración)."

    try:
        client = Groq(api_key=settings.GROQ_API_KEY)

        # ---- Definición del System Prompt ----
        # Personaliza este prompt para Senti
        system_prompt_content = (
            "Eres SentiBot, un asistente virtual experto de Senti. Senti es una empresa que [describe brevemente Senti: qué hace, a quién ayuda, sus principales productos/servicios]. "
            "Tu objetivo es ayudar a los usuarios respondiendo sus preguntas sobre Senti de manera clara, concisa y amigable. "
            "Si te preguntan algo que no está relacionado con Senti o no sabes la respuesta, indica amablemente que no puedes ayudar con esa consulta específica y sugiere que reformulen la pregunta o contacten a soporte si es un tema complejo."
            "Evita dar opiniones personales o hablar de temas fuera de tu rol como asistente de Senti."
            "Intenta ser breve en tus respuestas."
        )
        # ---- Fin Definición del System Prompt ----

        messages_for_groq = [{"role": "system", "content": system_prompt_content}]

        # Opcional: Añadir historial de chat si está disponible y es relevante
        if chat_history: # chat_history debería ser una lista de {"role": "user/assistant", "content": "..."}
            # Limita el historial para no exceder el límite de tokens
            # Aquí se puede implementar una lógica más sofisticada (ej. resumir, seleccionar mensajes clave)
            for msg in chat_history[-5:]: # Tomar los últimos 5 mensajes, por ejemplo
                messages_for_groq.append(msg)

        messages_for_groq.append({"role": "user", "content": user_query})

        # Modelos disponibles en Groq: "llama3-8b-8192", "llama3-70b-8192", "mixtral-8x7b-32768", "gemma-7b-it"
        # Elige el que mejor se adapte a tus necesidades y presupuesto (si aplica)
        # llama3-8b-8192 es una buena opción balanceada para empezar.
        chat_completion = client.chat.completions.create(
            messages=messages_for_groq,
            model="llama3-8b-8192", # O el modelo que prefieras de Groq
            temperature=0.7,        # Ajusta la creatividad (0.0 más determinista, 1.0 más creativo)
            max_tokens=300,         # Límite de tokens para la respuesta
            # top_p=1,              # Otra forma de controlar la aleatoriedad
            # stop=None,            # Secuencias para detener la generación
            # stream=False,         # Si quieres procesar la respuesta en trozos (más complejo de integrar aquí)
        )
        response_text = chat_completion.choices[0].message.content.strip()
        return response_text

    except Exception as e:
        logger.error(f"Error al interactuar con la API de Groq: {e}")
        # Considera si quieres dar un mensaje de error más técnico al usuario o uno genérico
        return "Lo siento, he encontrado un problema al intentar generar una respuesta. Por favor, inténtalo de nuevo más tarde."
# --- Fin función Groq ---


@method_decorator(csrf_exempt, name='dispatch')
class TelegramWebhookView(View):
    def post(self, request):
        try:
            data = json.loads(request.body.decode('utf-8'))
            logger.debug(f"Webhook recibido (raw data): {data}")
        except json.JSONDecodeError:
            logger.error("Error decodificando JSON del webhook.")
            return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

        if 'message' in data:
            self.handle_message(data['message'], raw_update=data)
        elif 'callback_query' in data:
            self.handle_callback_query(data['callback_query'], raw_update=data)
        else:
            logger.warning(f"Tipo de actualización no manejada recibida: {list(data.keys())}")
            return JsonResponse({"status": "ok", "message": "Update type not handled but acknowledged"})

        return JsonResponse({"status": "ok"})

    def handle_message(self, message_data, raw_update):
        if not TelegramChat or not TelegramMessage:
            logger.error("Modelos de Telegram no están disponibles en handle_message.")
            return

        message_id = message_data['message_id']
        chat_data = message_data['chat']
        chat_id = chat_data['id']
        text = message_data.get('text')
        message_date_timestamp = message_data.get('date')

        if message_date_timestamp:
            message_date = make_aware(datetime.fromtimestamp(message_date_timestamp))
        else:
            logger.warning(f"Mensaje {message_id} no tiene campo 'date'. Usando now().")
            message_date = make_aware(datetime.now())

        from_user_data = message_data.get('from', {})
        from_user_id = from_user_data.get('id')

        chat, created_chat = TelegramChat.objects.update_or_create(
            chat_id=chat_id,
            defaults={
                'type': chat_data.get('type', 'private'),
                'first_name': chat_data.get('first_name'),
                'last_name': chat_data.get('last_name'),
                'username': chat_data.get('username'),
            }
        )
        if created_chat:
            logger.info(f"Nuevo chat creado: {chat_id} (@{chat.username or chat.first_name or ''})")

        # Guardar el mensaje del usuario
        saved_message = None
        try:
            if not TelegramMessage.objects.filter(message_id=message_id, chat=chat).exists(): # Añadido chat para mayor precisión
                saved_message = TelegramMessage.objects.create(
                    message_id=message_id,
                    chat=chat,
                    from_user_id=from_user_id,
                    text=text,
                    date=message_date,
                    is_from_bot=False,
                    raw_update=raw_update
                )
                logger.info(f"Mensaje {message_id} de {chat_id} guardado.")
            else:
                logger.info(f"Mensaje {message_id} de {chat_id} ya existe, no se guarda ni procesa de nuevo.")
                return
        except Exception as e:
            logger.error(f"No se pudo guardar el mensaje {message_id} para el chat {chat_id}: {e}")
            return

        # Lógica de respuesta
        if text:
            user_text_lower_stripped = text.lower().strip()
            bot_response_text = None

            if user_text_lower_stripped.startswith('/start'):
                bot_response_text = f"¡Hola {chat.first_name or 'usuario'}! Soy SentiBot, tu asistente virtual para Senti. ¿En qué puedo ayudarte hoy?"
            elif user_text_lower_stripped.startswith('/help'):
                bot_response_text = (
                    "Puedes preguntarme sobre Senti, nuestros productos o servicios. \n"
                    "Comandos disponibles:\n"
                    "/start - Reiniciar conversación\n"
                    "/help - Mostrar esta ayuda"
                )
            else:
                # --- Lógica para obtener respuesta de Groq ---
                logger.info(f"Obteniendo respuesta de Groq para: '{text}'")

                # Opcional: Recuperar historial de chat para Groq
                # Esto es un ejemplo básico. Podrías querer más mensajes o lógica de resumen.
                # El historial debe ser una lista de dicts: {"role": "user"|"assistant", "content": "..."}
                # chat_history_for_groq = []
                # recent_messages = TelegramMessage.objects.filter(chat=chat).order_by('-date')[:6] # Últimos N mensajes (incluyendo el actual del usuario)
                # for msg in reversed(recent_messages): # Más antiguo a más nuevo
                #     if msg.message_id == message_id: continue # No incluir el mensaje actual del usuario si ya está en `text`
                #     role = "assistant" if msg.is_from_bot else "user"
                #     if msg.text: # Solo si hay texto
                #        chat_history_for_groq.append({"role": role, "content": msg.text})

                # bot_response_text = get_groq_response(text, chat_history=chat_history_for_groq)
                bot_response_text = get_groq_response(text) # Versión sin historial por simplicidad inicial

            if bot_response_text:
                send_telegram_message(chat_id, bot_response_text)
                # Guardar la respuesta del bot en la base de datos
                try:
                    # Generamos un message_id_bot único (esto es un placeholder, Telegram no nos da este ID)
                    # Podrías usar un UUID o un timestamp muy preciso, o simplemente no guardar message_id para respuestas de bot si no es crucial
                    # Lo importante es asociarlo al chat correcto y marcarlo como is_from_bot=True
                    bot_message_id_placeholder = f"bot_{message_id}_{int(datetime.now().timestamp())}"
                    TelegramMessage.objects.create(
                        message_id=bot_message_id_placeholder, # O gestiona esto de otra forma
                        chat=chat,
                        from_user_id=None, # O el ID de tu bot si lo tienes
                        text=bot_response_text,
                        date=make_aware(datetime.now()),
                        is_from_bot=True,
                        raw_update=None # No hay raw_update para mensajes enviados por el bot
                    )
                    logger.info(f"Respuesta del bot a {chat_id} guardada.")
                except Exception as e:
                    logger.error(f"No se pudo guardar la respuesta del bot para el chat {chat_id}: {e}")

        else:
            logger.info(f"Mensaje de {chat_id} sin texto. No se envía respuesta.")

    def handle_callback_query(self, callback_query_data, raw_update):
        # ... (código existente, sin cambios relevantes para Groq en este punto) ...
        query_id = callback_query_data['id']
        from_user_data = callback_query_data.get('from', {})
        from_user_id = from_user_data.get('id')

        message_info = callback_query_data.get('message')
        chat_instance = None
        if message_info:
            chat_instance = message_info.get('chat')

        data_payload = callback_query_data.get('data')

        logger.info(f"Callback query recibido: id={query_id}, from_user_id={from_user_id}, data={data_payload}")

        ack_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
        try:
            requests.post(ack_url, json={'callback_query_id': query_id}, timeout=5)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error al acusar recibo del callback query {query_id}: {e}")

        if chat_instance and data_payload:
            chat_id = chat_instance.get('id')
            if not chat_id:
                logger.warning(f"Callback query {query_id} no tiene chat_id en message.chat.")
                return

            # Aquí podrías, si el callback lo requiere, también llamar a Groq
            # Por ejemplo, si un botón es "Saber más sobre X"
            if data_payload.startswith("groq_query_"):
                query_for_groq = data_payload.replace("groq_query_", "").replace("_", " ") # Ejemplo
                bot_response = get_groq_response(f"Háblame sobre {query_for_groq}")
                send_telegram_message(chat_id, bot_response)
                # También guarda esta respuesta del bot
            elif data_payload == 'accion_ejemplo_1':
                send_telegram_message(chat_id, "Has pulsado el botón de ejemplo 1.")
            # ...
            else:
                send_telegram_message(chat_id, f"Callback recibido con datos: {data_payload}")
        else:
            logger.warning(f"Callback query {query_id} sin chat_instance o data_payload. No se procesa acción.")
# telegram_bot/views.py

import json
import logging
from datetime import datetime, timedelta
import secrets # Para generar tokens seguros
import re # Para extraer emails

import requests
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone # Importar timezone de Django
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError

from groq import Groq

# Modelos de la app 'api' y otras apps
from api.models import Usuario, Terapia, MiembroTerapia # Añade más según necesites
from packages.models import Purchase
from google_calendar.models import CalendarEvent
# from therapy.models import UserChallenge, EmotionalPath, DailyComponent

# Modelos del bot
from .models import TelegramChat, TelegramMessage # Ahora importamos directamente

# Utilidad de envío de emails
try:
    from emails.utils import send_brevo_email
except ImportError:
    send_brevo_email = None
    logging.warning("Función send_brevo_email no encontrada. La verificación por email no funcionará.")

logger = logging.getLogger(__name__)


# --- Funciones de utilidad (send_telegram_message como estaba) ---
def send_telegram_message(chat_id, text, parse_mode=None, reply_markup=None):
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN no está configurado.")
        return None
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    if parse_mode: payload['parse_mode'] = parse_mode
    if reply_markup: payload['reply_markup'] = json.dumps(reply_markup)
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Mensaje enviado a {chat_id}. Status: {response.status_code}. Respuesta: {response.text[:200]}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error enviando mensaje a {chat_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Respuesta de Telegram (error): {e.response.text}")
        return None

# --- Función para obtener respuesta de Groq (modificada para aceptar contexto de usuario) ---
def get_groq_response(user_query, chat_history=None, user_context_data=None):
    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY no está configurada en settings.")
        return "Lo siento, no puedo procesar tu solicitud en este momento (error de configuración)."
    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        system_prompt_content = (
            "Eres SentiBot, un asistente virtual experto de Senti. Senti es una empresa que ofrece servicios de terapia online y herramientas para el bienestar emocional. "
            "Tu objetivo es ayudar a los usuarios respondiendo sus preguntas sobre Senti. "
            "Si el usuario ha verificado su correo, puedes acceder a su información personal como terapias, compras y citas para dar respuestas más precisas. "
            "Si te preguntan algo que no está relacionado con Senti o no sabes la respuesta, indica amablemente que no puedes ayudar con esa consulta específica. "
            "Evita dar opiniones personales. Sé conciso y amigable. Si necesitas que el usuario verifique su identidad para una acción, indícalo."
            "Si una pregunta del usuario parece requerir acceso a su información personal (como 'mis citas', 'mi terapia', 'mis compras') y no está verificado, debes guiarlo para que proporcione su email para verificación, en lugar de responder directamente que no puedes sin verificar."
        )
        if user_context_data:
            system_prompt_content += f"\n\nContexto del usuario verificado (Nombre: {user_context_data.get('nombre', 'N/A')}):\n{user_context_data.get('summary_text', '')}"

        messages_for_groq = [{"role": "system", "content": system_prompt_content}]
        if chat_history:
            for msg in chat_history[-5:]: messages_for_groq.append(msg)
        messages_for_groq.append({"role": "user", "content": user_query})

        chat_completion = client.chat.completions.create(
            messages=messages_for_groq, model="llama3-8b-8192", temperature=0.7, max_tokens=500
        )
        response_text = chat_completion.choices[0].message.content.strip()
        return response_text
    except Exception as e:
        logger.error(f"Error al interactuar con la API de Groq: {e}")
        return "Lo siento, he encontrado un problema al intentar generar una respuesta. Por favor, inténtalo de nuevo más tarde."


@method_decorator(csrf_exempt, name='dispatch')
class TelegramWebhookView(View):
    
    def get_or_create_telegram_chat(self, chat_id_telegram, chat_data_telegram):
        # Asegúrate de que los valores por defecto para los nuevos campos estén aquí si es necesario,
        # aunque `is_awaiting_email_input` ya tiene un default=False en el modelo.
        chat, created = TelegramChat.objects.get_or_create(
            chat_id=chat_id_telegram,
            defaults={
                'type': chat_data_telegram.get('type', 'private'),
                'first_name': chat_data_telegram.get('first_name'),
                'last_name': chat_data_telegram.get('last_name'),
                'username': chat_data_telegram.get('username'),
                # 'is_awaiting_email_input': False, # Ya tiene default en el modelo
            }
        )
        if not created:
            updated = False
            if chat.first_name != chat_data_telegram.get('first_name'):
                chat.first_name = chat_data_telegram.get('first_name'); updated = True
            if chat.last_name != chat_data_telegram.get('last_name'):
                chat.last_name = chat_data_telegram.get('last_name'); updated = True
            if chat.username != chat_data_telegram.get('username'):
                chat.username = chat_data_telegram.get('username'); updated = True
            if updated:
                chat.save(update_fields=['first_name', 'last_name', 'username', 'updated_at'])
        return chat, created

    def save_telegram_message(self, chat_instance, message_id_telegram, from_user_id_telegram, text, date_timestamp, is_from_bot, raw_update=None):
        try:
            if message_id_telegram and not is_from_bot:
                 if TelegramMessage.objects.filter(chat=chat_instance, message_id_telegram=message_id_telegram).exists():
                    logger.info(f"Mensaje (TG:{message_id_telegram}) de chat {chat_instance.chat_id} ya existe.")
                    return None
            message_date = timezone.make_aware(datetime.fromtimestamp(date_timestamp)) if date_timestamp else timezone.now()
            msg = TelegramMessage.objects.create(
                message_id_telegram=message_id_telegram, chat=chat_instance, from_user_id=from_user_id_telegram,
                text=text, date=message_date, is_from_bot=is_from_bot, raw_update=raw_update if not is_from_bot else None
            )
            logger.info(f"Mensaje (ID Django:{msg.id}, TG:{message_id_telegram or 'BOT'}) de chat {chat_instance.chat_id} guardado.")
            return msg
        except Exception as e:
            logger.error(f"No se pudo guardar el mensaje (TG:{message_id_telegram}) para el chat {chat_instance.chat_id}: {e}", exc_info=True)
            if message_id_telegram and not is_from_bot and TelegramMessage.objects.filter(chat=chat_instance, message_id_telegram=message_id_telegram).exists():
                return None
            return False

    def send_and_save_bot_response(self, chat_instance, bot_text_response):
        if not bot_text_response:
            logger.warning(f"No se envió respuesta al chat {chat_instance.chat_id} porque el texto estaba vacío.")
            return
        bot_msg_db = self.save_telegram_message(
            chat_instance=chat_instance, message_id_telegram=None, from_user_id_telegram=None,
            text=bot_text_response, date_timestamp=None, is_from_bot=True
        )
        if bot_msg_db is False:
             logger.error(f"No se pudo guardar la respuesta del bot para el chat {chat_instance.chat_id} ANTES de enviar.")
        response_data = send_telegram_message(chat_instance.chat_id, bot_text_response)
        if bot_msg_db and not response_data :
            logger.warning(f"Respuesta del bot para {chat_instance.chat_id} guardada (ID:{bot_msg_db.id}) pero falló al enviar a Telegram.")

    def start_email_verification(self, chat_instance, email_to_verify, pending_action, original_query):
        chat_id = chat_instance.chat_id
        try:
            user = Usuario.objects.get(email__iexact=email_to_verify)
        except Usuario.DoesNotExist:
            self.send_and_save_bot_response(chat_instance, f"No encontramos una cuenta Senti asociada al correo {email_to_verify}. Por favor, verifica el correo e inténtalo de nuevo, o regístrate en Senti.")
            chat_instance.clear_verification_fields()
            chat_instance.is_awaiting_email_input = True # Dejar que intente de nuevo con otro email
            chat_instance.original_query_for_verification = original_query # Mantener la consulta original
            chat_instance.pending_action_after_verification = pending_action
            chat_instance.save()
            return

        if TelegramChat.objects.filter(user=user).exclude(chat_id=chat_id).exists():
            self.send_and_save_bot_response(chat_instance, f"El correo {email_to_verify} ya está asociado y verificado con otra cuenta de Telegram. Si crees que esto es un error, contacta a soporte.")
            chat_instance.clear_verification_fields()
            chat_instance.is_awaiting_email_input = False # No seguir pidiendo email para este caso
            chat_instance.save()
            return

        verification_code = "".join(secrets.choice("0123456789") for _ in range(6))
        expiry_time = timezone.now() + timedelta(minutes=10)

        chat_instance.verification_code = verification_code
        chat_instance.verification_code_email = user.email
        chat_instance.verification_code_expiry = expiry_time
        chat_instance.pending_action_after_verification = pending_action
        chat_instance.original_query_for_verification = original_query
        chat_instance.is_awaiting_email_input = False # Ya tenemos el email, ahora esperamos código
        chat_instance.save()

        if send_brevo_email:
            email_subject = "Tu código de verificación para SentiBot"
            email_context = {'nombre': user.nombre or user.email.split('@')[0], 'code': verification_code, 'year': timezone.now().year}
            email_sent_successfully = send_brevo_email(
                subject=email_subject, to_email=user.email,
                template_name="telegram_verification_code.html", # Ajustado, asumiendo que la plantilla está en 'emails/...'
                context=email_context
            )
            if email_sent_successfully:
                self.send_and_save_bot_response(chat_instance, f"Te hemos enviado un código de verificación a {user.email}. Por favor, ingrésalo aquí para continuar. El código expira en 10 minutos.")
            else:
                self.send_and_save_bot_response(chat_instance, "Hubo un problema al enviar el correo de verificación. Por favor, intenta más tarde. Puedes volver a escribir tu consulta cuando desees.")
                chat_instance.clear_verification_fields()
                chat_instance.save()
        else:
            logger.error("send_brevo_email no está disponible.")
            self.send_and_save_bot_response(chat_instance, "Lo siento, el servicio de envío de correos no está disponible. No puedo verificar tu email en este momento.")
            chat_instance.clear_verification_fields()
            chat_instance.save()

    def process_verification_code_input(self, chat_instance, entered_code):
        chat_id = chat_instance.chat_id
        if chat_instance.verification_code == entered_code.strip():
            try:
                user_to_link = Usuario.objects.get(email__iexact=chat_instance.verification_code_email)
                chat_instance.user = user_to_link
                chat_instance.email_verified_at = timezone.now()
                pending_action = chat_instance.pending_action_after_verification
                original_query = chat_instance.original_query_for_verification
                chat_instance.clear_verification_fields()
                chat_instance.save()
                self.send_and_save_bot_response(chat_instance, "¡Correo verificado exitosamente! 🎉 Ahora puedo ayudarte con tu información personal.")
                if original_query:
                    logger.info(f"Procesando acción pendiente: {pending_action} con query: {original_query} para usuario {user_to_link.email}")
                    user_context_data = self._get_user_context_for_groq(user_to_link, action_hint=pending_action)
                    bot_response = get_groq_response(original_query, user_context_data=user_context_data)
                    self.send_and_save_bot_response(chat_instance, bot_response)
                else:
                    self.send_and_save_bot_response(chat_instance, "Ya estás verificado. ¿En qué te puedo ayudar ahora?")
            except Usuario.DoesNotExist:
                self.send_and_save_bot_response(chat_instance, "Hubo un problema inesperado al verificar tu cuenta. Por favor, intenta el proceso de nuevo más tarde.")
                chat_instance.clear_verification_fields()
                chat_instance.save()
        else:
            self.send_and_save_bot_response(chat_instance, "El código de verificación es incorrecto. Por favor, inténtalo de nuevo. Revisa tu correo.")

    def _get_user_context_for_groq(self, user, action_hint=None):
        if not user: return None
        context = {"nombre": user.nombre or user.email.split('@')[0]}
        summary_parts = [f"Información para el usuario {context['nombre']} (Email: {user.email}, Tipo de cuenta: {user.tipo_cuenta})."]
        miembro_terapias = MiembroTerapia.objects.filter(usuario=user).select_related('terapia')
        if miembro_terapias.exists():
            summary_parts.append("Terapias Activas:")
            for mt in miembro_terapias:
                terapia_info = f"  - Terapia de tipo '{mt.terapia.get_tipo_display()}'"
                if mt.terapia.nombre_familia: terapia_info += f" (Familia: {mt.terapia.nombre_familia})"
                next_event = CalendarEvent.objects.filter(terapia=mt.terapia, start_time__gte=timezone.now()).order_by('start_time').first()
                if next_event: terapia_info += f". Próxima sesión: {next_event.start_time.strftime('%d %b %Y %H:%M')}."
                else: terapia_info += ". No hay próximas sesiones agendadas."
                summary_parts.append(terapia_info)
        else: summary_parts.append("Actualmente no estás en ninguna terapia.")
        purchases = Purchase.objects.filter(user=user, payment_status='completed').order_by('-purchase_date')[:2]
        if purchases.exists():
            summary_parts.append("Compras Recientes:")
            for p in purchases: summary_parts.append(f"  - Compra de {p.purchased_session_count} sesiones de {p.therapy_type_purchased} (quedan {p.remaining_sessions}), el {p.purchase_date.strftime('%d %b %Y')}.")
        next_general_events = CalendarEvent.objects.filter(user=user, start_time__gte=timezone.now()).order_by('start_time')[:3]
        if next_general_events:
            summary_parts.append("Próximas Citas en Calendario:")
            for event in next_general_events: summary_parts.append(f"  - {event.title} ({event.get_type_display()}) el {event.start_time.strftime('%d %b %Y %H:%M')}.")
        context["summary_text"] = "\n".join(summary_parts)
        return context

    def _extract_email_from_text(self, text):
        """Extrae la primera dirección de email válida de un texto."""
        # Expresión regular simple para emails. Puede no cubrir todos los casos borde.
        email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        match = re.search(email_regex, text)
        if match:
            email_candidate = match.group(0)
            try:
                validate_email(email_candidate) # Usar validador de Django
                return email_candidate
            except DjangoValidationError:
                return None
        return None

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
        message_id_telegram = message_data['message_id']
        chat_data_telegram = message_data['chat']
        chat_id_telegram = chat_data_telegram['id']
        user_text = message_data.get('text', "").strip()
        message_date_timestamp = message_data.get('date')
        from_user_data = message_data.get('from', {})
        from_user_id_telegram = from_user_data.get('id')

        chat_instance, _ = self.get_or_create_telegram_chat(chat_id_telegram, chat_data_telegram)
        user_msg_db = self.save_telegram_message(
            chat_instance, message_id_telegram, from_user_id_telegram, 
            user_text, message_date_timestamp, False, raw_update
        )
        if user_msg_db is None: return

        # --- Flujo de Verificación y Comandos ---

        # 1. ¿Está el chat esperando un CÓDIGO DE VERIFICACIÓN?
        if chat_instance.is_awaiting_verification_code_state():
            self.process_verification_code_input(chat_instance, user_text)
            return

        # 2. ¿Está el chat esperando que el usuario INGRESE SU EMAIL?
        if chat_instance.is_awaiting_email_input:
            extracted_email = self._extract_email_from_text(user_text)
            if extracted_email:
                # El usuario ingresó algo que parece un email, proceder a verificarlo
                # La acción pendiente y la query original ya deberían estar en chat_instance
                self.start_email_verification(
                    chat_instance,
                    extracted_email,
                    chat_instance.pending_action_after_verification or "ayuda_general_verificada",
                    chat_instance.original_query_for_verification or "Consulta general tras verificación."
                )
            else:
                # El usuario no ingresó un email válido, volver a pedir o dar opciones
                self.send_and_save_bot_response(chat_instance, "No parece que eso sea una dirección de correo válida. Por favor, escribe tu correo electrónico para continuar o escribe /cancelar si no deseas verificarlo ahora.")
                # Mantenemos is_awaiting_email_input = True
            return
            
        # 3. Comandos especiales
        if user_text.lower() == '/start': # Usar == para exactitud con /start
            welcome_msg = f"¡Hola {chat_instance.first_name or 'usuario'}! Soy SentiBot. "
            if chat_instance.user and chat_instance.email_verified_at:
                welcome_msg += f"Veo que ya has verificado tu correo ({chat_instance.user.email}). ¿En qué te puedo ayudar?"
            else:
                welcome_msg += "Puedes hacerme preguntas sobre Senti. Si necesitas acceder a tu información personal, te pediré tu correo para verificar tu identidad."
            self.send_and_save_bot_response(chat_instance, welcome_msg)
            # Resetear estados de verificación por si acaso al hacer /start
            chat_instance.clear_verification_fields()
            chat_instance.save()
            return

        elif user_text.lower() == '/help': # Usar ==
            help_message = (
                "Soy SentiBot, tu asistente para Senti.\n"
                "Puedes hacerme preguntas sobre Senti y nuestros servicios. "
                "Si necesitas acceder a información de tu cuenta (como terapias o compras), te guiaré para verificar tu correo.\n"
                "Comandos útiles:\n"
                "/start - Reiniciar la conversación.\n"
                "/mis_datos - (Requiere verificación) Para obtener un resumen de tu información.\n"
                "/desvincular_email - Para quitar la asociación de tu email con este chat.\n"
                "/cancelar - Para cancelar un proceso de verificación de email o código."
            )
            self.send_and_save_bot_response(chat_instance, help_message)
            return
        
        elif user_text.lower() == '/cancelar': # Usar ==
            if chat_instance.is_awaiting_email_input or chat_instance.is_awaiting_verification_code_state():
                original_query = chat_instance.original_query_for_verification
                chat_instance.clear_verification_fields()
                chat_instance.save()
                cancel_msg = "Proceso de verificación cancelado."
                if original_query:
                    cancel_msg += f"\n\nRespecto a tu consulta original '{original_query[:50]}...', ¿hay algo más en lo que pueda ayudarte de forma general sobre Senti?"
                else:
                    cancel_msg += "\n\n¿Hay algo más en lo que pueda ayudarte?"
                self.send_and_save_bot_response(chat_instance, cancel_msg)
            else:
                self.send_and_save_bot_response(chat_instance, "No hay ningún proceso de verificación activo para cancelar. ¿Cómo puedo ayudarte?")
            return

        elif user_text.lower() == '/desvincular_email': # Usar ==
            if chat_instance.user:
                old_email = chat_instance.user.email
                chat_instance.user = None
                chat_instance.email_verified_at = None
                chat_instance.clear_verification_fields()
                chat_instance.save()
                self.send_and_save_bot_response(chat_instance, f"Se ha desvinculado el correo {old_email} de este chat de Telegram. Para volver a acceder a tu información personal, necesitarás verificar tu correo nuevamente.")
            else:
                self.send_and_save_bot_response(chat_instance, "No hay ningún correo electrónico vinculado a este chat de Telegram actualmente.")
            return

        # 4. Determinar si la consulta requiere autenticación
        #    Podemos usar Groq para una primera pasada o palabras clave.
        #    Por simplicidad, mantendremos las palabras clave por ahora.
        keywords_require_auth = [
            "mis datos", "mis terapias", "mis compras", "mis citas", "mi perfil", "mi cuenta",
            "mi agenda", "mis sesiones", "estado de mi pedido", "cancelar terapia", "reagendar cita",
            "ver mi progreso", "historial de compras"
        ]
        query_requires_auth = user_text.lower().startswith('/mis_datos') or \
                              any(keyword in user_text.lower() for keyword in keywords_require_auth)

        if query_requires_auth:
            if chat_instance.user and chat_instance.email_verified_at:
                # Usuario verificado, obtener contexto y responder con Groq
                user_context_data = self._get_user_context_for_groq(chat_instance.user, action_hint="get_personal_data")
                bot_response = get_groq_response(user_text, user_context_data=user_context_data)
                self.send_and_save_bot_response(chat_instance, bot_response)
            else:
                # No verificado, pedir email
                chat_instance.pending_action_after_verification = "process_original_query"
                chat_instance.original_query_for_verification = user_text
                chat_instance.is_awaiting_email_input = True
                chat_instance.save()
                self.send_and_save_bot_response(chat_instance, "Para ayudarte con eso, necesito verificar tu identidad. Por favor, escribe el correo electrónico que tienes asociado a tu cuenta de Senti.")
            return

        # 5. Consulta general a Groq (si no es comando y no requiere autenticación explícita)
        user_context_for_general_query = None
        if chat_instance.user and chat_instance.email_verified_at: # Si ya está verificado, igual pasamos contexto
            user_context_for_general_query = self._get_user_context_for_groq(chat_instance.user, action_hint="general_query")
        
        bot_response_text = get_groq_response(user_text, user_context_data=user_context_for_general_query)
        
        # Post-procesamiento opcional: Si Groq sugiere verificar y el usuario no lo está, iniciar el flujo.
        # Esto es más avanzado y requiere que Groq esté "entrenado" para dar este tipo de sugerencias.
        # Por ahora, si Groq responde algo, lo enviamos.
        # if "verificar tu correo" in bot_response_text.lower() and not (chat_instance.user and chat_instance.email_verified_at):
        #     chat_instance.pending_action_after_verification = "process_original_query"
        #     chat_instance.original_query_for_verification = user_text
        #     chat_instance.is_awaiting_email_input = True
        #     chat_instance.save()
        #     self.send_and_save_bot_response(chat_instance, "Parece que para ayudarte mejor con esto necesitaría verificar tu identidad. Por favor, escribe el correo electrónico que tienes asociado a tu cuenta de Senti.")
        #     return
            
        self.send_and_save_bot_response(chat_instance, bot_response_text)


    def handle_callback_query(self, callback_query_data, raw_update):
        query_id = callback_query_data['id']
        # Lógica similar a antes. Si un callback lleva a una acción que requiere auth:
        # chat_id_telegram = callback_query_data['message']['chat']['id']
        # chat_instance, _ = self.get_or_create_telegram_chat(chat_id_telegram, callback_query_data['message']['chat'])
        # if callback_query_data['data'] == "accion_requiere_auth":
        #     if chat_instance.user and chat_instance.email_verified_at:
        #         # ... hacer la acción ...
        #     else:
        #         # Guardar la intención y pedir email
        #         chat_instance.pending_action_after_verification = "accion_requiere_auth_callback"
        #         chat_instance.original_query_for_verification = f"Acción de callback: {callback_query_data['data']}"
        #         chat_instance.is_awaiting_email_input = True
        #         chat_instance.save()
        #         self.send_and_save_bot_response(chat_instance, "Para realizar esta acción, necesito verificar tu identidad. Por favor, escribe el correo electrónico asociado a tu cuenta de Senti.")
        
        ack_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
        try:
            requests.post(ack_url, json={'callback_query_id': query_id}, timeout=5)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error al acusar recibo del callback query {query_id}: {e}")
        logger.info(f"Callback query no manejado explícitamente o completado: {callback_query_data.get('data')}")
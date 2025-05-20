# telegram_bot/views.py

import json
import logging
from datetime import datetime, timedelta
import secrets # Para generar tokens seguros

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

# --- (CONVERSATION_STATE ya no es tan necesario si guardamos el estado en TelegramChat) ---
# CONVERSATION_STATE = {}

# --- Funciones de utilidad (send_telegram_message como estaba) ---
def send_telegram_message(chat_id, text, parse_mode=None, reply_markup=None):
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN no está configurado.")
        return None # Devuelve None o False para indicar fallo
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
        )
        if user_context_data: # user_context_data es un string con la info del usuario
            system_prompt_content += f"\n\nContexto del usuario verificado (Nombre: {user_context_data.get('nombre', 'N/A')}):\n{user_context_data.get('summary_text', '')}"

        messages_for_groq = [{"role": "system", "content": system_prompt_content}]
        if chat_history: # chat_history debería ser una lista de {"role": "user/assistant", "content": "..."}
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
        chat, created = TelegramChat.objects.get_or_create(
            chat_id=chat_id_telegram,
            defaults={
                'type': chat_data_telegram.get('type', 'private'),
                'first_name': chat_data_telegram.get('first_name'),
                'last_name': chat_data_telegram.get('last_name'),
                'username': chat_data_telegram.get('username'),
            }
        )
        if not created: # Si ya existía, actualizamos por si cambió nombre/username
            updated = False
            if chat.first_name != chat_data_telegram.get('first_name'):
                chat.first_name = chat_data_telegram.get('first_name')
                updated = True
            if chat.last_name != chat_data_telegram.get('last_name'):
                chat.last_name = chat_data_telegram.get('last_name')
                updated = True
            if chat.username != chat_data_telegram.get('username'):
                chat.username = chat_data_telegram.get('username')
                updated = True
            if updated:
                chat.save(update_fields=['first_name', 'last_name', 'username', 'updated_at'])
        return chat, created

    def save_telegram_message(self, chat_instance, message_id_telegram, from_user_id_telegram, text, date_timestamp, is_from_bot, raw_update=None):
        try:
            # Evitar duplicados si Telegram reenvía (basado en message_id_telegram y chat)
            if message_id_telegram and not is_from_bot: # Solo para mensajes de usuario con ID de Telegram
                 if TelegramMessage.objects.filter(chat=chat_instance, message_id_telegram=message_id_telegram).exists():
                    logger.info(f"Mensaje (TG:{message_id_telegram}) de chat {chat_instance.chat_id} ya existe. No se guarda ni procesa de nuevo.")
                    return None # Indica que no se procese más

            message_date = timezone.make_aware(datetime.fromtimestamp(date_timestamp)) if date_timestamp else timezone.now()

            msg = TelegramMessage.objects.create(
                message_id_telegram=message_id_telegram, # Puede ser None si es un mensaje del bot aún no enviado
                chat=chat_instance,
                from_user_id=from_user_id_telegram,
                text=text,
                date=message_date,
                is_from_bot=is_from_bot,
                raw_update=raw_update if not is_from_bot else None
            )
            logger.info(f"Mensaje (ID Django:{msg.id}, TG:{message_id_telegram or 'BOT'}) de chat {chat_instance.chat_id} guardado.")
            return msg
        except Exception as e: # Podría ser un IntegrityError por unique_together si hay race condition
            logger.error(f"No se pudo guardar el mensaje (TG:{message_id_telegram}) para el chat {chat_instance.chat_id}: {e}", exc_info=True)
            # Re-chequear si ya existe, por si fue una race condition
            if message_id_telegram and not is_from_bot and TelegramMessage.objects.filter(chat=chat_instance, message_id_telegram=message_id_telegram).exists():
                return None
            return False # Indica error

    def send_and_save_bot_response(self, chat_instance, bot_text_response):
        """Envía la respuesta del bot y la guarda en la BD."""
        if not bot_text_response:
            logger.warning(f"No se envió respuesta al chat {chat_instance.chat_id} porque el texto estaba vacío.")
            return

        # Primero guardamos el mensaje del bot (sin message_id_telegram aún)
        bot_msg_db = self.save_telegram_message(
            chat_instance=chat_instance,
            message_id_telegram=None, # Se actualizará después si Telegram devuelve uno
            from_user_id_telegram=None, # Es del bot
            text=bot_text_response,
            date_timestamp=None, # se usará timezone.now()
            is_from_bot=True
        )
        
        if bot_msg_db is False: # Error al guardar
             logger.error(f"No se pudo guardar la respuesta del bot para el chat {chat_instance.chat_id} ANTES de enviar.")
             # Podrías decidir enviar igualmente si el guardado falla.
             # Por ahora, si no se guarda, no se envía para consistencia.
             # return

        # Luego enviamos a Telegram
        response_data = send_telegram_message(chat_instance.chat_id, bot_text_response)

        if response_data and response_data.get('ok'):
            # Actualizar el mensaje del bot en la BD con el message_id de Telegram si lo tenemos
            # Esto es opcional, pero útil si quieres relacionar respuestas específicas.
            # Sin embargo, la API sendMessage no devuelve el message_id del mensaje enviado por el bot en la respuesta directa.
            # Para obtener el message_id del mensaje del bot, necesitarías otra lógica (ej. si usas Inline Keyboards y obtienes updates).
            # Por ahora, no actualizaremos el message_id_telegram del mensaje del bot.
            pass
        elif bot_msg_db: # Si el envío falló pero se guardó
            logger.warning(f"Respuesta del bot para {chat_instance.chat_id} guardada (ID:{bot_msg_db.id}) pero falló al enviar a Telegram.")
            # Podrías marcar este mensaje en la BD como "envío_fallido"
            # bot_msg_db.send_status = 'failed'
            # bot_msg_db.save()

    # --- Lógica de verificación de email ---
    def start_email_verification(self, chat_instance, email_to_verify, pending_action, original_query):
        chat_id = chat_instance.chat_id
        try:
            user = Usuario.objects.get(email__iexact=email_to_verify) # Case-insensitive
        except Usuario.DoesNotExist:
            send_telegram_message(chat_id, f"No encontramos una cuenta Senti asociada al correo {email_to_verify}. Por favor, verifica el correo o regístrate en Senti.")
            chat_instance.clear_verification_fields() # Limpiar cualquier intento previo
            chat_instance.save()
            return

        # Comprobar si este email ya está verificado y asociado a OTRO chat de Telegram
        # Esto previene que un usuario "robe" la asociación de otro chat de Telegram si conoce el email
        if TelegramChat.objects.filter(user=user).exclude(chat_id=chat_id).exists():
            send_telegram_message(chat_id, f"El correo {email_to_verify} ya está asociado y verificado con otra cuenta de Telegram. Si crees que esto es un error, contacta a soporte.")
            chat_instance.clear_verification_fields()
            chat_instance.save()
            return

        verification_code = "".join(secrets.choice("0123456789") for _ in range(6))
        expiry_time = timezone.now() + timedelta(minutes=10)

        chat_instance.verification_code = verification_code
        chat_instance.verification_code_email = user.email # Guardamos el email canonico de la BD
        chat_instance.verification_code_expiry = expiry_time
        chat_instance.pending_action_after_verification = pending_action
        chat_instance.original_query_for_verification = original_query
        chat_instance.save()

        if send_brevo_email:
            email_subject = "Tu código de verificación para SentiBot"
            email_context = {'nombre': user.nombre or user.email.split('@')[0], 'code': verification_code, 'year': timezone.now().year}
            
            email_sent_successfully = send_brevo_email(
                subject=email_subject,
                to_email=user.email,
                template_name="emails/telegram_verification_code.html", # Asegúrate que la ruta sea correcta
                context=email_context
            )
            if email_sent_successfully:
                send_telegram_message(chat_id, f"Te hemos enviado un código de verificación a {user.email}. Por favor, ingrésalo aquí para continuar. El código expira en 10 minutos.")
            else:
                send_telegram_message(chat_id, "Hubo un problema al enviar el correo de verificación. Por favor, intenta más tarde.")
                chat_instance.clear_verification_fields() # Limpiar si el email no se pudo enviar
                chat_instance.save()
        else:
            logger.error("send_brevo_email no está disponible. No se puede enviar código de verificación.")
            send_telegram_message(chat_id, "Lo siento, el servicio de envío de correos no está disponible en este momento. No puedo verificar tu email.")
            chat_instance.clear_verification_fields()
            chat_instance.save()

    def process_verification_code_input(self, chat_instance, entered_code):
        chat_id = chat_instance.chat_id
        
        if chat_instance.verification_code == entered_code.strip():
            # Código correcto y no expirado (ya chequeado en is_awaiting_verification_code)
            try:
                user_to_link = Usuario.objects.get(email__iexact=chat_instance.verification_code_email)
                
                # Si el usuario ya estaba vinculado a OTRO chat, y ese chat tenia 'user'
                # Este es un caso delicado. Podríamos desvincular el anterior o impedirlo.
                # Por ahora, el OneToOneField en TelegramChat.user debería prevenirlo si se asigna.
                # Si el TelegramChat.user ya tiene un usuario y es diferente, ¿qué hacer?
                # Por ahora, asumimos que si llegamos aquí, estamos listos para (re)vincular.

                chat_instance.user = user_to_link
                chat_instance.email_verified_at = timezone.now()
                
                pending_action = chat_instance.pending_action_after_verification
                original_query = chat_instance.original_query_for_verification
                
                chat_instance.clear_verification_fields() # Limpiar campos de verificación
                chat_instance.save()

                send_telegram_message(chat_id, "¡Correo verificado exitosamente! 🎉 Ahora puedo ayudarte con tu información personal.")
                
                # Procesar la acción pendiente
                if original_query: # Si había una consulta original, intentamos responderla ahora
                    logger.info(f"Procesando acción pendiente: {pending_action} con query: {original_query} para usuario {user_to_link.email}")
                    user_context_data = self._get_user_context_for_groq(user_to_link, action_hint=pending_action)
                    bot_response = get_groq_response(original_query, user_context_data=user_context_data)
                    self.send_and_save_bot_response(chat_instance, bot_response)
                else: # Si no, un mensaje genérico
                    self.send_and_save_bot_response(chat_instance, "Ya estás verificado. ¿En qué te puedo ayudar ahora?")

            except Usuario.DoesNotExist: # No debería pasar si start_email_verification funcionó
                send_telegram_message(chat_id, "Hubo un problema inesperado al verificar tu cuenta. Por favor, intenta el proceso de nuevo.")
                chat_instance.clear_verification_fields()
                chat_instance.save()
        else:
            send_telegram_message(chat_id, "El código de verificación es incorrecto. Por favor, inténtalo de nuevo. Revisa tu correo.")
            # No limpiamos el código aquí, para que pueda reintentar hasta que expire.

    def _get_user_context_for_groq(self, user, action_hint=None):
        """Prepara un string de contexto sobre el usuario para Groq."""
        if not user: return None

        context = {"nombre": user.nombre or user.email.split('@')[0]}
        summary_parts = [f"Información para el usuario {context['nombre']} (Email: {user.email}, Tipo de cuenta: {user.tipo_cuenta})."]

        # Basado en action_hint, podríamos ser más específicos.
        # Por ejemplo, si action_hint == "get_my_therapies"
        
        # Terapias
        miembro_terapias = MiembroTerapia.objects.filter(usuario=user).select_related('terapia')
        if miembro_terapias.exists():
            summary_parts.append("Terapias Activas:")
            for mt in miembro_terapias:
                terapia_info = f"  - Terapia de tipo '{mt.terapia.get_tipo_display()}'"
                if mt.terapia.nombre_familia: terapia_info += f" (Familia: {mt.terapia.nombre_familia})"
                
                next_event = CalendarEvent.objects.filter(
                    terapia=mt.terapia, start_time__gte=timezone.now()
                ).order_by('start_time').first()
                if next_event:
                    terapia_info += f". Próxima sesión agendada: {next_event.start_time.strftime('%d %b %Y %H:%M')}."
                else:
                    terapia_info += ". No hay próximas sesiones agendadas para esta terapia."
                summary_parts.append(terapia_info)
        else:
            summary_parts.append("Actualmente no estás en ninguna terapia.")

        # Compras Recientes
        purchases = Purchase.objects.filter(user=user, payment_status='completed').order_by('-purchase_date')[:2]
        if purchases.exists():
            summary_parts.append("Compras Recientes:")
            for p in purchases:
                summary_parts.append(f"  - Compra de {p.purchased_session_count} sesiones de {p.therapy_type_purchased} (quedan {p.remaining_sessions}), el {p.purchase_date.strftime('%d %b %Y')}.")
        
        # Próximas Citas Generales (no solo de terapia)
        next_general_events = CalendarEvent.objects.filter(user=user, start_time__gte=timezone.now()).order_by('start_time')[:3]
        if next_general_events:
            summary_parts.append("Próximas Citas en Calendario:")
            for event in next_general_events:
                summary_parts.append(f"  - {event.title} ({event.get_type_display()}) el {event.start_time.strftime('%d %b %Y %H:%M')}.")

        context["summary_text"] = "\n".join(summary_parts)
        return context

    # --- Manejador Principal POST ---
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

    # --- Manejador de Mensajes ---
    def handle_message(self, message_data, raw_update):
        # Extraer datos básicos del mensaje
        message_id_telegram = message_data['message_id']
        chat_data_telegram = message_data['chat']
        chat_id_telegram = chat_data_telegram['id']
        user_text = message_data.get('text', "").strip()
        message_date_timestamp = message_data.get('date')
        from_user_data = message_data.get('from', {})
        from_user_id_telegram = from_user_data.get('id')

        # Obtener o crear el chat y guardar el mensaje del usuario
        chat_instance, _ = self.get_or_create_telegram_chat(chat_id_telegram, chat_data_telegram)
        
        # Guardar mensaje del usuario. Si retorna None, es un duplicado, no procesar.
        user_msg_db = self.save_telegram_message(
            chat_instance, message_id_telegram, from_user_id_telegram, 
            user_text, message_date_timestamp, False, raw_update
        )
        if user_msg_db is None: # Duplicado o error grave al guardar
            return

        # --- Flujo de Verificación y Comandos ---
        # 1. ¿Está el chat esperando un código de verificación?
        if chat_instance.is_awaiting_verification_code():
            self.process_verification_code_input(chat_instance, user_text)
            return # La función de verificación se encarga de responder

        # 2. ¿Está el chat esperando un email? (Se maneja por comando /verificar_email <email>)
        # Ya no usamos CONVERSATION_STATE para esto, el usuario debe ser explícito.

        # 3. Comandos especiales
        if user_text.lower().startswith('/start'):
            welcome_msg = f"¡Hola {chat_instance.first_name or 'usuario'}! Soy SentiBot. "
            if chat_instance.user and chat_instance.email_verified_at:
                welcome_msg += f"Veo que ya has verificado tu correo ({chat_instance.user.email}). ¿En qué te puedo ayudar?"
            else:
                welcome_msg += "Puedes preguntarme sobre Senti, o si quieres acceder a tu información personal, usa el comando /verificar_email tu@correo.com"
            self.send_and_save_bot_response(chat_instance, welcome_msg)
            return

        elif user_text.lower().startswith('/help'):
            help_message = (
                "Soy SentiBot, tu asistente para Senti.\n"
                "Comandos útiles:\n"
                "/start - Reiniciar conversación.\n"
                "/verificar_email <tu_correo@ejemplo.com> - Para acceder a tu información personal.\n"
                "/mis_datos - (Requiere verificación) Para obtener un resumen de tu información.\n"
                "/desvincular_email - Para quitar la asociación de tu email con este chat de Telegram.\n\n"
                "También puedes hacerme preguntas generales sobre Senti."
            )
            self.send_and_save_bot_response(chat_instance, help_message)
            return

        elif user_text.lower().startswith('/verificar_email'):
            parts = user_text.split()
            if len(parts) > 1:
                email_to_verify = parts[1]
                try:
                    validate_email(email_to_verify) # Validación básica de formato
                    # La acción pendiente por defecto será "ayuda_general_verificada"
                    # La consulta original puede ser la propia solicitud de verificación
                    self.start_email_verification(chat_instance, email_to_verify, "ayuda_general_verificada", user_text)
                except DjangoValidationError:
                    self.send_and_save_bot_response(chat_instance, "El formato del correo electrónico no es válido. Ejemplo: /verificar_email tu@correo.com")
            else:
                self.send_and_save_bot_response(chat_instance, "Por favor, incluye tu correo. Ejemplo: /verificar_email tu@correo.com")
            return
        
        elif user_text.lower().startswith('/desvincular_email'):
            if chat_instance.user:
                old_email = chat_instance.user.email
                chat_instance.user = None
                chat_instance.email_verified_at = None
                chat_instance.clear_verification_fields() # También limpia códigos pendientes
                chat_instance.save()
                self.send_and_save_bot_response(chat_instance, f"Se ha desvinculado el correo {old_email} de este chat de Telegram. Para volver a acceder a tu información personal, necesitarás verificar tu correo nuevamente.")
            else:
                self.send_and_save_bot_response(chat_instance, "No hay ningún correo electrónico vinculado a este chat de Telegram actualmente.")
            return

        # 4. Consultas que requieren verificación (ej. /mis_datos o palabras clave)
        # Puedes definir palabras clave o comandos específicos
        keywords_require_auth = ["mis datos", "mis terapias", "mis compras", "mis citas", "mi perfil"]
        query_requires_auth = user_text.lower().startswith('/mis_datos') or any(keyword in user_text.lower() for keyword in keywords_require_auth)

        if query_requires_auth:
            if chat_instance.user and chat_instance.email_verified_at:
                # Usuario verificado, obtener contexto y responder con Groq
                user_context_data = self._get_user_context_for_groq(chat_instance.user, action_hint="get_personal_data")
                bot_response = get_groq_response(user_text, user_context_data=user_context_data)
                self.send_and_save_bot_response(chat_instance, bot_response)
            else:
                # No verificado, pedir verificación
                chat_instance.pending_action_after_verification = "process_original_query"
                chat_instance.original_query_for_verification = user_text
                chat_instance.save() # Guardar la intención
                self.send_and_save_bot_response(chat_instance, "Para responder a tu consulta sobre información personal, necesito verificar tu identidad. Por favor, usa el comando:\n/verificar_email tu@correo.com")
            return

        # 5. Consulta general a Groq (si no es comando y no requiere autenticación explícita)
        # Si el usuario está verificado, igual pasamos un contexto básico por si Groq lo usa.
        user_context_for_general_query = None
        if chat_instance.user and chat_instance.email_verified_at:
            user_context_for_general_query = self._get_user_context_for_groq(chat_instance.user, action_hint="general_query")
        
        bot_response_text = get_groq_response(user_text, user_context_data=user_context_for_general_query)
        self.send_and_save_bot_response(chat_instance, bot_response_text)


    def handle_callback_query(self, callback_query_data, raw_update):
        # (Lógica para callbacks, similar a antes. Si un callback requiere datos de usuario,
        #  chequear chat_instance.user y chat_instance.email_verified_at)
        # ...
        query_id = callback_query_data['id']
        # ... (resto de tu lógica de callback_query)
        # Ejemplo:
        # chat_id_telegram = callback_query_data['message']['chat']['id']
        # chat_data_telegram = callback_query_data['message']['chat']
        # chat_instance, _ = self.get_or_create_telegram_chat(chat_id_telegram, chat_data_telegram)
        #
        # if callback_query_data['data'] == "accion_requiere_auth":
        #     if chat_instance.user and chat_instance.email_verified_at:
        #         # Hacer algo
        #     else:
        #         send_telegram_message(chat_id_telegram, "Necesitas verificar tu email primero. Usa /verificar_email tu@correo.com")
        
        # Acusar recibo del callback query
        ack_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
        try:
            requests.post(ack_url, json={'callback_query_id': query_id}, timeout=5)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error al acusar recibo del callback query {query_id}: {e}")

        logger.info(f"Callback query no manejado explícitamente: {callback_query_data.get('data')}")
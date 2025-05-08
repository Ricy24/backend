# google_calendar/views.py

from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.utils import timezone
from django.shortcuts import get_object_or_404
from api.models import Terapia, MiembroTerapia, Usuario
from packages.models import Purchase # Importar Purchase
from .models import CalendarEvent
from psychologist.models import Availability # PsychologistProfile no se usa directamente aquí
from emails.utils import send_brevo_email
import logging
import uuid
from django.conf import settings
from datetime import timedelta, datetime
from whatsapp.services import send_whatsapp_message 
from .tasks import send_session_reminder_whatsapp_task


# CONFIGURACIÓN (Mover a settings.py si es posible)
CANCELATION_POLICY_HOURS = getattr(settings, 'CANCELATION_POLICY_HOURS', 2)
SESSION_DURATION_MINUTES = getattr(settings, 'SESSION_DURATION_MINUTES', 60)
FREE_SESSION_DURATION_MINUTES = getattr(settings, 'FREE_SESSION_DURATION_MINUTES', 30)
FREE_SESSION_TITLE = getattr(settings, 'FREE_SESSION_TITLE', "Sesión Gratuita de Terapia")

REMINDER_MINUTES_BEFORE = 5
REMINDER_MINUTES_BEFORE_TASK = 5 # O el valor que necesites para la tarea

logger = logging.getLogger(__name__)

class CalendarEventListView(APIView):
    """
    Lista los eventos del calendario para el usuario autenticado.
    Incluye eventos donde es paciente y donde es psicóloga (si aplica).
    Calcula si el usuario puede agendar una sesión gratuita.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            now = timezone.now()
            # Umbral para incluir eventos pasados recientes (ej. 1 hora)
            past_threshold = now - timedelta(hours=1)

            # Eventos donde el usuario es el paciente (user)
            patient_events = CalendarEvent.objects.filter(
                user=user,
                # type__in=['therapy', 'personal'], # Podrías querer todos sus tipos
                start_time__gte=past_threshold
            ).select_related('psychologist', 'terapia').order_by('start_time')

            # Eventos donde el usuario es la psicóloga (psychologist)
            psychologist_events = CalendarEvent.objects.none() # Iniciar vacío
            if user.is_psychologist:
                psychologist_events = CalendarEvent.objects.filter(
                    psychologist=user,
                    type__in=['therapy', 'group'], # Tipos relevantes para psicóloga
                    start_time__gte=past_threshold
                ).select_related('user', 'terapia').order_by('start_time')

            # Combinar y eliminar duplicados si un evento aparece en ambos roles (poco probable)
            # Usar union() es más eficiente si los querysets son compatibles
            # events_qs = patient_events.union(psychologist_events).order_by('start_time')
            # O simplemente combinar las listas después de formatear si la unión da problemas
            all_events = list(patient_events) + list(psychologist_events)
            # Eliminar duplicados basados en ID si es necesario (si user puede ser psychologist en el mismo evento)
            unique_event_ids = set()
            distinct_events = []
            for event in sorted(all_events, key=lambda e: e.start_time):
                if event.event_id not in unique_event_ids:
                    distinct_events.append(event)
                    unique_event_ids.add(event.event_id)


            # Formatear respuesta
            data = []
            for event in distinct_events:
                jitsi_meet_link = None
                # Lógica para mostrar enlace Jitsi
                if event.type == 'therapy' and event.start_time.date() == now.date():
                    if now >= event.start_time - timedelta(minutes=10):
                        # Usar enlace existente o generar uno nuevo si no existe y es necesario
                        jitsi_meet_link = event.jitsi_meet_link or event.generate_jitsi_meet_link()
                        # Nota: generate_jitsi_meet_link debería guardar el evento

                event_data = {
                    'id': event.event_id,
                    'title': event.title,
                    'start_time': event.start_time.isoformat(),
                    'end_time': event.end_time.isoformat(),
                    'type': event.type,
                    'get_type_display': event.get_type_display(), # Añadir texto legible
                    'description': event.description,
                    'terapia_id': event.terapia.id if event.terapia else None,
                    'terapia_info': event.terapia.__str__() if event.terapia else None, # Añadir info legible
                    'jitsi_meet_link': jitsi_meet_link,
                    'purchase_used_id': event.purchase_used_id # Mostrar si se guardó
                }

                # Añadir información de roles
                if event.psychologist == user: # El usuario es la psicóloga de este evento
                    event_data['role'] = 'psychologist'
                    if event.user: # Añadir info del paciente
                        event_data['patient'] = {
                            'id': event.user.id,
                            'nombre': event.user.nombre or event.user.email.split('@')[0],
                            'email': event.user.email,
                        }
                elif event.user == user: # El usuario es el paciente de este evento
                     event_data['role'] = 'patient'
                     if event.psychologist: # Añadir info de la psicóloga
                         event_data['psychologist'] = {
                             'id': event.psychologist.id,
                             'nombre': event.psychologist.nombre or event.psychologist.email.split('@')[0],
                             'email': event.psychologist.email,
                             'profile_pic': event.psychologist.profile_pic.url if hasattr(event.psychologist, 'profile_pic') and event.psychologist.profile_pic else None
                         }
                else: # Evento personal del usuario (sin psicólogo)
                    event_data['role'] = 'personal_user'


                data.append(event_data)

            # Verificar si el usuario (paciente) puede agendar una sesión gratuita
            can_schedule_free_session = False
            if not user.is_psychologist:
                 # Buscar si ya tuvo una sesión gratuita *completada* o *futura*
                 has_completed_or_future_free_session = CalendarEvent.objects.filter(
                     user=user,
                     type='therapy',
                     # Basarse en el título o descripción puede ser frágil, mejor un flag si es posible
                     title=FREE_SESSION_TITLE
                 ).filter(Q(end_time__lte=now) | Q(start_time__gte=now)).exists()
                 can_schedule_free_session = not has_completed_or_future_free_session

            logger.debug(f"Eventos devueltos para {user.email}: {len(data)}")
            return Response({
                'events': data,
                'can_schedule_free_session': can_schedule_free_session
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en CalendarEventListView para usuario {request.user.email}: {str(e)}", exc_info=True)
            return Response({'error': 'Error interno al obtener los eventos del calendario'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CalendarEventCreateView(APIView):
    """
    Crea un nuevo evento en el calendario.
    Maneja sesiones de terapia (gratuitas y pagadas) y eventos personales.
    Distingue entre usar créditos de una terapia específica y créditos individuales genéricos.
    Verifica disponibilidad, conflictos y descuenta créditos de la compra correcta.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        event_data = request.data
        logger.info(f"Intento de creación de evento por {user.email}. Datos: {event_data}")

        try:
            # --- Extraer y Validar Datos de Entrada ---
            title = event_data.get('title')
            start_time_str = event_data.get('start_time')
            end_time_str = event_data.get('end_time')
            event_type = event_data.get('type', 'personal') # 'personal' por defecto
            description = event_data.get('description', '')
            # IDs pueden ser None
            terapia_id = event_data.get('terapia_id')
            psychologist_id = event_data.get('psychologist_id')
            # Flag explícito para sesión gratuita es MÁS ROBUSTO que basarse en el título
            is_free_session_request = event_data.get('is_free_session', False) or title == FREE_SESSION_TITLE

            if not title or not start_time_str or not end_time_str:
                logger.warning("Faltan campos requeridos (title, start_time, end_time)")
                return Response({'error': 'Los campos title, start_time y end_time son requeridos'}, status=status.HTTP_400_BAD_REQUEST)

            try:
                start_time_obj = timezone.datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                end_time_obj = timezone.datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
            except ValueError:
                 logger.warning(f"Error de formato de fecha: start={start_time_str}, end={end_time_str}")
                 return Response(
                     {'error': 'Formato de fecha inválido. Use ISO 8601 (YYYY-MM-DDTHH:MM:SSZ)'},
                     status=status.HTTP_400_BAD_REQUEST
                 )

            if start_time_obj >= end_time_obj:
                logger.warning("Error de lógica de fechas: end_time no es posterior a start_time")
                return Response({'error': 'La hora de finalización debe ser posterior a la hora de inicio'}, status=status.HTTP_400_BAD_REQUEST)

            if start_time_obj < timezone.now():
                logger.warning("Intento de crear evento en el pasado")
                return Response({'error': 'No se pueden crear eventos en el pasado'}, status=status.HTTP_400_BAD_REQUEST)
            # --- Fin Validación de Datos de Entrada ---

            terapia = None # Terapia asociada al evento (puede ser None)
            psychologist = None # Psicóloga asociada (solo para 'therapy')
            purchase_to_use = None # Compra de donde se descontará (solo para pagada)

            # --- Lógica Específica para Tipo 'therapy' ---
            if event_type == 'therapy':
                logger.info("Procesando creación de evento tipo 'therapy'")

                if user.is_psychologist:
                    logger.warning(f"Psicóloga {user.email} intentó crear evento de terapia para sí misma")
                    return Response({'error': 'Las psicólogas no pueden crear eventos de terapia desde esta interfaz'}, status=status.HTTP_403_FORBIDDEN)

                # Validar Psicólogo
                if not psychologist_id:
                    logger.warning("Falta psychologist_id para evento de terapia")
                    return Response({'error': 'Debes seleccionar una psicóloga para la sesión de terapia'}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    # Asegurar que el ID corresponde a una psicóloga activa/válida si tienes esos estados
                    psychologist = Usuario.objects.get(id=psychologist_id, is_psychologist=True)
                    # Opcional: Verificar si la psicóloga está activa
                    # if not psychologist.is_active or not psychologist.psychologist_profile.is_approved:
                    #     return Response({'error': 'La psicóloga seleccionada no está disponible actualmente'}, status=status.HTTP_400_BAD_REQUEST)
                    logger.debug(f"Psicóloga seleccionada: {psychologist.email} (ID: {psychologist.id})")
                except Usuario.DoesNotExist:
                     logger.warning(f"Psicóloga con ID {psychologist_id} no encontrada")
                     return Response({'error': 'Psicóloga no encontrada'}, status=status.HTTP_404_NOT_FOUND)

                # Validar Duración según tipo de sesión
                session_duration_expected_minutes = FREE_SESSION_DURATION_MINUTES if is_free_session_request else SESSION_DURATION_MINUTES
                session_duration_expected = timedelta(minutes=session_duration_expected_minutes)
                session_duration_actual = end_time_obj - start_time_obj

                if session_duration_actual != session_duration_expected:
                     logger.warning(f"Duración incorrecta: Esperada {session_duration_expected}, Recibida {session_duration_actual}")
                     return Response(
                         {'error': f'La duración de la sesión debe ser de {session_duration_expected_minutes} minutos para {"sesiones gratuitas" if is_free_session_request else "terapias regulares"}'},
                         status=status.HTTP_400_BAD_REQUEST
                     )

                # --- Sub-Lógica: Sesión Gratuita ---
                if is_free_session_request:
                    logger.info("Validando sesión gratuita...")
                    # Verificar si la psicóloga la ofrece (si tienes ese campo)
                    if hasattr(psychologist, 'psychologist_profile') and not psychologist.psychologist_profile.offers_free_30min_session:
                        logger.warning(f"Intento de agendar gratuita con psicóloga {psychologist.email} que no la ofrece")
                        return Response({'error': f'{psychologist.nombre} no ofrece la sesión gratuita de {FREE_SESSION_DURATION_MINUTES} minutos'}, status=status.HTTP_400_BAD_REQUEST)

                    # Verificar si el usuario ya usó su sesión gratuita
                    has_completed_or_future_free_session = CalendarEvent.objects.filter(
                        user=user,
                        type='therapy',
                        title=FREE_SESSION_TITLE # O filtrar por un flag/campo específico
                    ).filter(Q(end_time__lte=timezone.now()) | Q(start_time__gte=timezone.now())).exists()

                    if has_completed_or_future_free_session:
                        logger.warning(f"Usuario {user.email} ya usó o tiene agendada su sesión gratuita")
                        return Response({'error': 'Ya has utilizado o tienes agendada tu sesión gratuita'}, status=status.HTTP_403_FORBIDDEN)

                    # Validar Terapia asociada (opcional para gratuitas, pero si se envía, validar)
                    if terapia_id:
                        try:
                            terapia = Terapia.objects.get(id=terapia_id)
                            if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                                logger.warning(f"Usuario {user.email} intentó agendar gratuita en terapia {terapia_id} a la que no pertenece")
                                return Response({'error': 'No eres miembro de la terapia especificada'}, status=status.HTTP_403_FORBIDDEN)
                            logger.debug(f"Sesión gratuita asociada a terapia existente ID: {terapia.id}")
                        except Terapia.DoesNotExist:
                            logger.warning(f"Terapia {terapia_id} no encontrada para sesión gratuita")
                            return Response({'error': 'La terapia especificada no existe'}, status=status.HTTP_404_NOT_FOUND)
                    # Si no hay terapia_id, `terapia` sigue siendo None para la gratuita

                    logger.info("Validaciones para sesión gratuita superadas.")
                # --- Fin Sub-Lógica: Sesión Gratuita ---

                # --- Sub-Lógica: Sesión Regular (Pagada) ---
                else:
                    logger.info("Validando sesión regular (requiere créditos)...")
                    # CASO 1: Se especificó una Terapia (el usuario quiere usar créditos de esa terapia)
                    if terapia_id:
                        logger.debug(f"Intentando usar créditos de terapia específica ID: {terapia_id}")
                        try:
                            terapia = Terapia.objects.get(id=terapia_id)
                            if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                                logger.warning(f"Usuario {user.email} intentó agendar en terapia {terapia_id} a la que no pertenece")
                                return Response({'error': 'No eres miembro de esta terapia'}, status=status.HTTP_403_FORBIDDEN)

                            # Buscar compras válidas asociadas a ESTA terapia específica
                            # El tipo de crédito debe coincidir con el tipo de terapia
                            purchase_query = Purchase.objects.filter(
                                terapia=terapia,
                                payment_status='completed',
                                remaining_sessions__gt=0,
                                # Descomentar si es estricto: therapy_type_purchased=terapia.tipo
                            ).order_by('purchase_date') # Usar la más antigua primero

                            if not purchase_query.exists():
                                logger.warning(f"No se encontraron créditos válidos para la terapia específica {terapia_id} (Tipo: {terapia.tipo})")
                                return Response({'error': f'No tienes sesiones compradas disponibles para esta terapia específica ({terapia.get_tipo_display()}).'}, status=status.HTTP_403_FORBIDDEN)

                            purchase_to_use = purchase_query.first()
                            logger.info(f"Crédito encontrado para terapia específica {terapia_id}. Usando compra ID: {purchase_to_use.id} (Tipo: {purchase_to_use.therapy_type_purchased})")

                        except Terapia.DoesNotExist:
                            logger.warning(f"Terapia específica {terapia_id} no encontrada")
                            return Response({'error': 'La terapia especificada no existe'}, status=status.HTTP_404_NOT_FOUND)

                    # CASO 2: NO se especificó Terapia (el usuario quiere usar créditos individuales genéricos)
                    else:
                        logger.debug(f"Intentando usar créditos individuales genéricos de {user.email}")
                        purchase_query = Purchase.objects.filter(
                            user=user,
                            terapia__isnull=True, # Sin terapia asociada
                            therapy_type_purchased='individual', # De tipo individual
                            payment_status='completed',
                            remaining_sessions__gt=0
                        ).order_by('purchase_date') # Usar la más antigua

                        if not purchase_query.exists():
                            logger.warning(f"No se encontraron créditos individuales genéricos válidos para {user.email}")
                            return Response({'error': 'No tienes sesiones individuales genéricas compradas disponibles. Compra un paquete individual o selecciona una terapia específica si tienes créditos para ella.'}, status=status.HTTP_403_FORBIDDEN)

                        purchase_to_use = purchase_query.first()
                        # IMPORTANTE: `terapia` sigue siendo `None` en este caso
                        logger.info(f"Crédito individual genérico encontrado. Usando compra ID: {purchase_to_use.id}")

                # --- Fin Sub-Lógica: Sesión Regular (Pagada) ---

                # --- Verificación de Disponibilidad y Conflictos (Común para terapia gratuita y pagada) ---
                logger.debug(f"Verificando disponibilidad para {psychologist.email} en {start_time_obj}")
                # Corregido: Usar day_of_week en inglés para comparar con el modelo Availability
                day_of_week_str = start_time_obj.strftime('%A').lower() # ej: 'monday'

                try:
                    availability = Availability.objects.get(
                        psychologist=psychologist,
                        day_of_week__iexact=day_of_week_str # Comparación insensible a mayúsculas
                    )
                except Availability.DoesNotExist:
                    logger.warning(f"No hay registro de disponibilidad para {psychologist.email} el día {day_of_week_str}")
                    # Formatear el nombre del día para el mensaje de error
                    day_name_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][start_time_obj.weekday()]
                    return Response({'error': f"La psicóloga {psychologist.nombre} no tiene configurada disponibilidad para los {day_name_es}"}, status=status.HTTP_400_BAD_REQUEST)
                except Availability.MultipleObjectsReturned:
                     logger.error(f"Error crítico: Múltiples registros de disponibilidad para {psychologist.email} el día {day_of_week_str}")
                     # Deberías arreglar esto en los datos o en la lógica de guardado de Availability
                     return Response({'error': 'Error de configuración de disponibilidad de la psicóloga. Contacta a soporte.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


                # Crear datetimes conscientes de zona horaria local para comparar
                local_tz = timezone.get_current_timezone() # Obtiene la zona horaria (ej: ZoneInfo('America/Bogota'))

                # Combina la fecha de la sesión con la hora de inicio/fin de disponibilidad (crea un datetime naive)
                naive_avail_start = datetime.combine(start_time_obj.date(), availability.start_time)
                naive_avail_end = datetime.combine(start_time_obj.date(), availability.end_time)

                # Haz los datetimes conscientes usando replace() con la zona horaria local
                avail_start = naive_avail_start.replace(tzinfo=local_tz)
                avail_end = naive_avail_end.replace(tzinfo=local_tz)

                # Comparar directamente los datetimes conscientes (esta parte ya estaba bien)
                if not (avail_start <= start_time_obj and end_time_obj <= avail_end):
                     logger.warning(f"Horario fuera de disponibilidad: Sesión {start_time_obj.time()}-{end_time_obj.time()}, Disponible {availability.start_time}-{availability.end_time} (Zona: {local_tz})")
                     return Response({'error': f'La hora seleccionada ({start_time_obj.strftime("%H:%M")}) está fuera del horario disponible ({availability.start_time.strftime("%H:%M")} - {availability.end_time.strftime("%H:%M")}) de la psicóloga para ese día.'}, status=status.HTTP_400_BAD_REQUEST)

                # Verificar conflictos con otros eventos de la PSICÓLOGA
                conflicts = CalendarEvent.objects.filter(
                    psychologist=psychologist,
                    # Considerar todos los tipos que bloquean el tiempo de la psicóloga
                    # type__in=['therapy', 'group', 'personal_psychologist', 'unavailable'],
                    start_time__lt=end_time_obj, # Un evento existente empieza antes de que termine el nuevo
                    end_time__gt=start_time_obj  # Un evento existente termina después de que empiece el nuevo
                ).exists()

                if conflicts:
                    logger.warning(f"Conflicto de horario detectado para {psychologist.email} en {start_time_obj}")
                    return Response({'error': 'La psicóloga ya tiene otra sesión o evento programado en este horario'}, status=status.HTTP_409_CONFLICT)

                logger.debug("Verificación de disponibilidad y conflictos superada.")
                # --- Fin Verificación Disponibilidad y Conflictos ---

                # --- Descontar Sesión Comprada (si aplica) ---
                if not is_free_session_request:
                    if not purchase_to_use:
                        # Seguridad: Si llegó aquí sin `purchase_to_use`, algo falló antes
                        logger.error(f"Error crítico: Intentando agendar sesión pagada para {user.email} sin una compra identificada.")
                        return Response({'error': 'Error interno al verificar los créditos de sesión. No se pudo identificar la compra a utilizar.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                    # Descontar de la compra identificada
                    purchase_to_use.remaining_sessions -= 1
                    purchase_to_use.save(update_fields=['remaining_sessions'])
                    logger.info(f"Sesión descontada de la compra ID {purchase_to_use.id}. Sesiones restantes: {purchase_to_use.remaining_sessions}")

            # --- Fin Lógica Específica para Tipo 'therapy' ---

            # --- Crear el Evento en Base de Datos ---
            event = CalendarEvent.objects.create(
                user=user,
                # Usar un UUID más estándar para event_id
                event_id=f"evt_{uuid.uuid4().hex}",
                title=title,
                start_time=start_time_obj,
                end_time=end_time_obj,
                type=event_type,
                description=description or (f"Sesión con {psychologist.nombre}" if event_type == 'therapy' and psychologist else ''),
                # Asignar terapia solo si se usó una específica (no para genéricas individuales ni personales)
                terapia=terapia if event_type == 'therapy' and terapia_id else None,
                psychologist=psychologist if event_type == 'therapy' else None,
                # Guardar referencia a la compra usada para facilitar cancelaciones/reembolsos
                purchase_used=purchase_to_use if event_type == 'therapy' and not is_free_session_request else None
            )
            logger.info(f"Evento creado con ID: {event.event_id}, Tipo: {event.type}, Terapia asociada: {event.terapia.id if event.terapia else 'Ninguna'}, Compra usada: {event.purchase_used_id if event.purchase_used else 'N/A'}")

            # --- Generar Enlace Jitsi y Enviar Correos (solo para 'therapy') ---
            jitsi_meet_link = None
            if event_type == 'therapy':
                now = timezone.now()
                # Generar enlace si aplica (misma lógica que en ListView)
                if event.start_time.date() == now.date() and now >= event.start_time - timedelta(minutes=10):
                     jitsi_meet_link = event.generate_jitsi_meet_link()
                     logger.info(f"Enlace Jitsi generado para evento {event.event_id}: {jitsi_meet_link}")

                # Enviar correos de confirmación
                try:
                    user_name = user.nombre or user.email.split('@')[0]
                    psychologist_name = psychologist.nombre or psychologist.email.split('@')[0]
                    # Usar la variable calculada is_free_session_request
                    session_type_str = 'Gratuita' if is_free_session_request else 'Regular'

                    # Contexto base para correos
                    base_context = {
                        'session_date': start_time_obj.strftime('%Y-%m-%d'),
                        'session_time': start_time_obj.strftime('%H:%M %Z'), # Incluir zona horaria
                        'session_type': session_type_str,
                        'session_duration': f"{session_duration_expected_minutes} minutos",
                        'terapia_id': event.terapia.id if event.terapia else None,
                        'terapia_display': event.terapia.get_tipo_display() if event.terapia else 'Individual (Genérica)',
                        'description': event.description[:500] if event.description else 'Sin descripción adicional.',
                        'year': now.year,
                        'support_contact': getattr(settings, 'SUPPORT_EMAIL', 'soporte@senti.lat'),
                        'platform_name': getattr(settings, 'PLATFORM_NAME', 'Senti'),
                        'jitsi_meet_link': jitsi_meet_link if jitsi_meet_link else f'El enlace estará disponible 10 minutos antes de la sesión ({start_time_obj.strftime("%H:%M")}) en tu calendario.',
                        'cancel_policy_hours': CANCELATION_POLICY_HOURS
                    }

                    # Contexto y envío para el paciente
                    patient_context = base_context.copy()
                    patient_context.update({
                        'nombre': user_name,
                        'psychologist_name': psychologist_name,
                        'psychologist_email': psychologist.email,
                        'dashboard_url': getattr(settings, 'FRONTEND_URL', 'https://senti.lat') + '/dashboard', # Ajustar URL
                    })
                    send_brevo_email(
                        subject=f"Confirmación de tu Sesión de Terapia {session_type_str}",
                        to_email=user.email,
                        template_name="therapy_confirmation_email.html", # Asegúrate que existe
                        context=patient_context
                    )
                    logger.info(f"Correo de confirmación de paciente enviado a {user.email} para evento {event.event_id}")

                    # Contexto y envío para la psicóloga
                    psychologist_context = base_context.copy()
                    psychologist_context.update({
                        'psychologist_name': psychologist_name,
                        'patient_name': user_name,
                        'patient_email': user.email,
                        'dashboard_url': getattr(settings, 'FRONTEND_URL', 'https://app.senti.lat') + '/dashboard/psychologist', # Ajustar URL
                    })
                    send_brevo_email(
                        subject=f"Nueva Sesión {session_type_str} Programada",
                        to_email=psychologist.email,
                        template_name="psychologist_session_confirmation.html", # Asegúrate que existe
                        context=psychologist_context
                    )
                    logger.info(f"Correo de notificación a psicóloga enviado a {psychologist.email} para evento {event.event_id}")

                except Exception as e:
                    # No fallar la creación del evento si el correo falla, solo loguear
                    logger.error(f"Error al enviar correos de confirmación para evento {event.event_id}: {str(e)}", exc_info=True)
            # --- Fin Generar Jitsi y Enviar Correos ---

            # --- INICIO: Notificaciones WhatsApp ---
            # Esta sección va DESPUÉS de que el 'event' se ha creado y guardado
            # y después (o en paralelo) del envío de correos.

            if event.type == 'therapy' and event.psychologist: # Solo para sesiones de terapia con psicólogo
                patient = event.user
                psychologist_obj = event.psychologist # Renombrado para evitar conflicto con la variable psychologist de más arriba
                session_time_local = event.start_time.astimezone(timezone.get_current_timezone())

                # Reutilizamos is_free_session_request que ya calculaste al principio de la vista
                # is_truly_free_session = is_free_session_request # Esta variable ya la tienes definida arriba
                
                session_type_display = "Gratuita de Bienvenida" if is_free_session_request else "Regular"
                
                formatted_date = session_time_local.strftime("%d de %B de %Y")
                formatted_time = session_time_local.strftime("%I:%M %p %Z")

                # --- 1. Mensaje de Confirmación para el Paciente ---
                if patient.telefono: # Asegúrate que tu modelo Usuario (patient) tenga el campo 'telefono'
                    patient_name_display = patient.nombre or patient.email.split('@')[0]
                    psychologist_name_display = psychologist_obj.nombre or psychologist_obj.email.split('@')[0]
                    
                    confirmation_message_patient = f"""¡Hola {patient_name_display}! 👋
Tu sesión de Terapia {session_type_display} con la psicóloga {psychologist_name_display} ha sido confirmada.

🗓️ Fecha: {formatted_date}
⏰ Hora: {formatted_time}

Recibirás un recordatorio con el enlace para unirte {REMINDER_MINUTES_BEFORE} minutos antes de la sesión.
¡Te esperamos en Senti!"""
                    
                    wa_success_patient, wa_resp_patient = send_whatsapp_message(patient.telefono, confirmation_message_patient)
                    if wa_success_patient:
                        logger.info(f"WhatsApp de confirmación de sesión enviado a paciente {patient.email} (Tel: {patient.telefono})")
                    else:
                        logger.error(f"Error enviando WhatsApp de confirmación a paciente {patient.email} (Tel: {patient.telefono}): {wa_resp_patient}")

                # --- 2. Mensaje de Confirmación para la Psicóloga ---
                if psychologist_obj.telefono: # Asegúrate que tu modelo Usuario (psychologist_obj) tenga 'telefono'
                    patient_name_display = patient.nombre or patient.email.split('@')[0]
                    psychologist_name_display = psychologist_obj.nombre or psychologist_obj.email.split('@')[0]

                    confirmation_message_psychologist = f"""¡Hola Psic. {psychologist_name_display}! 🔔
Tienes una nueva sesión de Terapia {session_type_display} agendada:

👤 Paciente: {patient_name_display} ({patient.email})
🗓️ Fecha: {formatted_date}
⏰ Hora: {formatted_time}

Se enviará un recordatorio automático al paciente con el enlace {REMINDER_MINUTES_BEFORE} minutos antes.
Plataforma Senti."""
                    wa_success_psychologist, wa_resp_psychologist = send_whatsapp_message(psychologist_obj.telefono, confirmation_message_psychologist)
                    if wa_success_psychologist:
                        logger.info(f"WhatsApp de confirmación de sesión enviado a psicóloga {psychologist_obj.email} (Tel: {psychologist_obj.telefono})")
                    else:
                        logger.error(f"Error enviando WhatsApp de confirmación a psicóloga {psychologist_obj.email} (Tel: {psychologist_obj.telefono}): {wa_resp_psychologist}")

                # --- 3. Programar Tarea de Recordatorio (requiere Celery) ---
                reminder_time_utc = event.start_time - timedelta(minutes=REMINDER_MINUTES_BEFORE)

                if reminder_time_utc > timezone.now():
                    # DEBES IMPORTAR ESTA TAREA AL INICIO DEL ARCHIVO:
                    # from google_calendar.tasks import send_session_reminder_whatsapp_task 
                    # O la ruta correcta donde definas la tarea Celery.
                    
                    # Programar para el paciente
                    if patient.telefono:
                        logger.info(f"Programando recordatorio de WhatsApp para paciente {patient.email} (Evento ID: {event.id}) a las {reminder_time_utc.isoformat()}")
                        # send_session_reminder_whatsapp_task.apply_async(
                        #    args=[
                        #        event.id, 
                        #        patient.telefono, 
                        #        patient.nombre or patient.email.split('@')[0], 
                        #        "patient", 
                        #        psychologist_obj.nombre or psychologist_obj.email.split('@')[0]
                        #    ],
                        #    eta=reminder_time_utc
                        # )
                        logger.warning(f"TAREA CELERY (recordatorio paciente para evento {event.id}) PENDIENTE DE DESCOMENTAR Y CONFIGURAR.")


                    # Programar para la psicóloga (opcional)
                    if psychologist_obj.telefono:
                        logger.info(f"Programando recordatorio de WhatsApp para psicóloga {psychologist_obj.email} (Evento ID: {event.id}) a las {reminder_time_utc.isoformat()}")
                        # send_session_reminder_whatsapp_task.apply_async(
                        #    args=[
                        #        event.id, 
                        #        psychologist_obj.telefono, 
                        #        psychologist_obj.nombre or psychologist_obj.email.split('@')[0], 
                        #        "psychologist", 
                        #        patient.nombre or patient.email.split('@')[0]
                        #    ],
                        #    eta=reminder_time_utc
                        # )
                        logger.warning(f"TAREA CELERY (recordatorio psicóloga para evento {event.id}) PENDIENTE DE DESCOMENTAR Y CONFIGURAR.")
                else:
                    logger.info(f"No se programó recordatorio para evento {event.id} porque la hora del recordatorio ya pasó.")

            # --- FIN: Notificaciones WhatsApp ---

            # --- Preparar Respuesta Exitosa ---
            response_data = {
                'id': event.event_id,
                'title': event.title,
                'start_time': event.start_time.isoformat(),
                'end_time': event.end_time.isoformat(),
                'type': event.type,
                'get_type_display': event.get_type_display(),
                'description': event.description,
                'terapia_id': event.terapia.id if event.terapia else None,
                'terapia_info': event.terapia.__str__() if event.terapia else ('Individual Genérica' if event.type == 'therapy' else None),
                'jitsi_meet_link': jitsi_meet_link,
                'purchase_used_id': event.purchase_used_id,
                'psychologist': {
                    'id': psychologist.id,
                    'nombre': psychologist.nombre or psychologist.email.split('@')[0],
                    'email': psychologist.email,
                    'profile_pic': psychologist.profile_pic.url if hasattr(psychologist, 'profile_pic') and psychologist.profile_pic else None
                } if psychologist else None
            }
            logger.info(f"Evento {event.event_id} creado exitosamente para usuario {user.email}.")
            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error inesperado en CalendarEventCreateView para usuario {user.email}: {str(e)}", exc_info=True)
            # Evitar exponer detalles internos en producción
            return Response({'error': 'Ocurrió un error inesperado al crear el evento. Por favor, inténtalo de nuevo más tarde.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CalendarEventUpdateView(APIView):
    """
    Actualiza un evento existente en el calendario.
    Permite al usuario (paciente) modificar sus propios eventos.
    Si se cambia la hora/fecha de una terapia, re-verifica disponibilidad y conflictos.
    """
    permission_classes = [IsAuthenticated]

    def put(self, request, event_id):
        user = request.user
        logger.info(f"Intento de actualización de evento {event_id} por usuario {user.email}. Datos: {request.data}")

        try:
            # El usuario solo puede actualizar sus propios eventos
            event = get_object_or_404(CalendarEvent, event_id=event_id, user=user)

            original_start_time = event.start_time # Guardar para comparación

            # --- Extraer datos de la solicitud (usar valores existentes como default) ---
            title = request.data.get('title', event.title)
            start_time_str = request.data.get('start_time')
            end_time_str = request.data.get('end_time')
            # El tipo de evento probablemente no debería cambiar (ej. de terapia a personal)
            # event_type = request.data.get('type', event.type)
            description = request.data.get('description', event.description)

            start_time_changed = False
            new_start_time = event.start_time
            new_end_time = event.end_time

            # --- Validar y actualizar fechas si se proporcionan ---
            if start_time_str:
                try:
                    new_start_time = timezone.datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    start_time_changed = new_start_time != event.start_time
                except ValueError:
                    return Response({'error': 'Formato de fecha de inicio inválido.'}, status=status.HTTP_400_BAD_REQUEST)

            if end_time_str:
                 try:
                    new_end_time = timezone.datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                    # Si solo se cambia end_time, también se considera cambio de horario
                    if not start_time_changed:
                        start_time_changed = new_end_time != event.end_time
                 except ValueError:
                    return Response({'error': 'Formato de fecha de fin inválido.'}, status=status.HTTP_400_BAD_REQUEST)

            # Validar lógica de fechas nuevas
            if new_start_time >= new_end_time:
                return Response({'error': 'La hora de finalización debe ser posterior a la hora de inicio'}, status=status.HTTP_400_BAD_REQUEST)
            if new_start_time < timezone.now():
                 # Permitir editar eventos que acaban de empezar? Quizás un pequeño margen.
                if new_start_time < timezone.now() - timedelta(minutes=5):
                    return Response({'error': 'No se pueden mover eventos al pasado'}, status=status.HTTP_400_BAD_REQUEST)

            # --- Re-validar disponibilidad/conflictos si la hora cambió y es terapia ---
            if start_time_changed and event.type == 'therapy' and event.psychologist:
                logger.info(f"Revalidando disponibilidad para evento {event_id} por cambio de horario a {new_start_time}")
                psychologist = event.psychologist # Ya lo tenemos en el evento
                day_of_week_str = new_start_time.strftime('%A').lower()
                session_duration = new_end_time - new_start_time # Usar nueva duración

                try:
                    availability = Availability.objects.get(psychologist=psychologist, day_of_week__iexact=day_of_week_str)
                    local_tz = timezone.get_current_timezone() # Obtiene la zona horaria

                    # Combina la nueva fecha con la hora de inicio/fin de disponibilidad (crea un datetime naive)
                    naive_avail_start = datetime.combine(new_start_time.date(), availability.start_time)
                    naive_avail_end = datetime.combine(new_start_time.date(), availability.end_time)

                    # Haz los datetimes conscientes usando replace()
                    avail_start = naive_avail_start.replace(tzinfo=local_tz)
                    avail_end = naive_avail_end.replace(tzinfo=local_tz)

                    if not (avail_start <= new_start_time and new_end_time <= avail_end):
                         logger.warning(f"Nuevo horario {new_start_time}-{new_end_time} fuera de disponibilidad {avail_start}-{avail_end}")
                         return Response({'error': 'La nueva hora seleccionada está fuera del horario disponible de la psicóloga para ese día.'}, status=status.HTTP_400_BAD_REQUEST)

                    # Verificar conflictos, EXCLUYENDO el propio evento que se está modificando
                    conflicts = CalendarEvent.objects.filter(
                        psychologist=psychologist,
                        start_time__lt=new_end_time,
                        end_time__gt=new_start_time
                    ).exclude(event_id=event_id).exists()

                    if conflicts:
                        logger.warning(f"Conflicto detectado para nuevo horario de evento {event_id}")
                        return Response({'error': 'La psicóloga ya tiene otra sesión u evento en el nuevo horario seleccionado'}, status=status.HTTP_409_CONFLICT)
                    logger.debug("Revalidación de disponibilidad/conflicto superada.")

                except Availability.DoesNotExist:
                    day_name_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][new_start_time.weekday()]
                    logger.warning(f"No hay disponibilidad configurada para el nuevo día {day_name_es}")
                    return Response({'error': f"La psicóloga no tiene configurada disponibilidad para los {day_name_es}"}, status=status.HTTP_400_BAD_REQUEST)
                except Availability.MultipleObjectsReturned:
                     logger.error(f"Error crítico: Múltiples disponibilidades para {psychologist.email} el {day_of_week_str}")
                     return Response({'error': 'Error de configuración de disponibilidad. Contacta a soporte.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # --- Actualizar campos del evento ---
            event.title = title
            event.start_time = new_start_time
            event.end_time = new_end_time
            # event.type = event_type # No permitir cambio de tipo usualmente
            event.description = description

            # Invalidar/borrar enlace Jitsi si la fecha/hora cambió significativamente
            if start_time_changed and event.jitsi_meet_link:
                # Podríamos solo borrarlo si el día cambia, o si la hora cambia más de X minutos
                if event.start_time.date() != original_start_time.date():
                     event.jitsi_meet_link = None
                     event.jitsi_meet_room = None # Borrar también el nombre de la sala
                     logger.info(f"Enlace Jitsi invalidado para evento {event_id} debido a cambio de fecha/hora.")

            event.save() # Guardar todos los cambios

            # --- Re-generar enlace Jitsi si es necesario ---
            jitsi_meet_link = event.jitsi_meet_link # Usar el actual si existe y no se invalidó
            now = timezone.now()
            if not jitsi_meet_link and event.type == 'therapy': # Si no hay enlace (porque se borró o nunca se creó)
                 if event.start_time.date() == now.date() and now >= event.start_time - timedelta(minutes=10):
                      jitsi_meet_link = event.generate_jitsi_meet_link() # Guardará el evento de nuevo
                      logger.info(f"Nuevo enlace Jitsi generado para evento actualizado {event_id}")

            # --- Enviar correos de actualización (si es terapia) ---
            if event.type == 'therapy':
                try:
                    # Reutilizar lógica de correos de creación pero con plantilla/asunto de actualización
                    user_name = event.user.nombre or event.user.email.split('@')[0]
                    psychologist_name = event.psychologist.nombre or event.psychologist.email.split('@')[0]
                    is_free_session_event = event.title == FREE_SESSION_TITLE # Basado en el título guardado
                    session_type_str = 'Gratuita' if is_free_session_event else 'Regular'
                    session_duration_minutes = (event.end_time - event.start_time).total_seconds() / 60

                    base_context = { # Contexto con datos actualizados
                        'session_date': event.start_time.strftime('%Y-%m-%d'),
                        'session_time': event.start_time.strftime('%H:%M %Z'),
                        'session_type': session_type_str,
                        'session_duration': f"{session_duration_minutes:.0f} minutos",
                        'terapia_id': event.terapia.id if event.terapia else None,
                        'terapia_display': event.terapia.get_tipo_display() if event.terapia else 'Individual (Genérica)',
                        'description': event.description[:500] if event.description else 'Sin descripción adicional.',
                        'year': now.year,
                        'support_contact': getattr(settings, 'SUPPORT_EMAIL', 'soporte@senti.lat'),
                        'platform_name': getattr(settings, 'PLATFORM_NAME', 'Senti'),
                        'jitsi_meet_link': jitsi_meet_link if jitsi_meet_link else f'El enlace estará disponible 10 minutos antes de la sesión ({event.start_time.strftime("%H:%M")}) en tu calendario.',
                        'cancel_policy_hours': CANCELATION_POLICY_HOURS
                    }
                    # Enviar correo al paciente
                    patient_context = base_context.copy()
                    patient_context.update({ 'nombre': user_name, 'psychologist_name': psychologist_name, 'dashboard_url': '...' })
                    send_brevo_email(subject=f"Actualización de tu Sesión de Terapia {session_type_str}", to_email=event.user.email, template_name="therapy_update_email.html", context=patient_context)
                    logger.info(f"Correo de actualización de paciente enviado a {event.user.email} para evento {event.event_id}")

                    # Enviar correo a la psicóloga
                    psychologist_context = base_context.copy()
                    psychologist_context.update({'psychologist_name': psychologist_name, 'patient_name': user_name, 'dashboard_url': '...'})
                    send_brevo_email(subject=f"Sesión {session_type_str} Actualizada con {user_name}", to_email=event.psychologist.email, template_name="psychologist_session_update.html", context=psychologist_context)
                    logger.info(f"Correo de actualización a psicóloga enviado a {event.psychologist.email} para evento {event.event_id}")

                except Exception as e:
                    logger.error(f"Error al enviar correos de actualización para evento {event_id}: {str(e)}", exc_info=True)


            logger.info(f"Evento {event_id} actualizado exitosamente por {user.username}")
            # --- Preparar Respuesta Exitosa ---
            return Response({
                'id': event.event_id,
                'title': event.title,
                'start_time': event.start_time.isoformat(),
                'end_time': event.end_time.isoformat(),
                'type': event.type,
                'get_type_display': event.get_type_display(),
                'description': event.description,
                'terapia_id': event.terapia.id if event.terapia else None,
                'terapia_info': event.terapia.__str__() if event.terapia else ('Individual Genérica' if event.type == 'therapy' else None),
                'jitsi_meet_link': jitsi_meet_link,
                'purchase_used_id': event.purchase_used_id,
                'psychologist': { # ... datos psicólogo ...
                } if event.psychologist else None,
                'patient': { # ... datos paciente ...
                }
            }, status=status.HTTP_200_OK)

        except CalendarEvent.DoesNotExist:
             logger.warning(f"Intento de actualizar evento no existente o no autorizado: {event_id} por usuario {user.username}")
             return Response({'error': 'Evento no encontrado o no tienes permiso para actualizarlo'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error inesperado en CalendarEventUpdateView para evento {event_id}: {str(e)}", exc_info=True)
            return Response({'error': 'Error interno del servidor al actualizar el evento'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CalendarEventDeleteView(APIView):
    """
    Elimina un evento del calendario.
    Permite al usuario (paciente) eliminar sus propios eventos.
    Si se cancela una sesión de terapia pagada con suficiente antelación,
    intenta devolver el crédito a la compra correspondiente (si se guardó la referencia)
    o a una compra compatible.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, event_id):
        user = request.user
        logger.info(f"Intento de eliminación de evento {event_id} por usuario {user.email}")

        try:
            # El usuario solo puede borrar sus propios eventos
            event = get_object_or_404(CalendarEvent, event_id=event_id, user=user)

            session_returned = False
            purchase_refunded_id = None
            message = 'Evento eliminado con éxito.' # Mensaje por defecto

            # --- Lógica de Devolución de Crédito (Solo para terapia pagada) ---
            # Verificar si es terapia, no es gratuita y si se guardó la compra usada
            is_refundable_type = event.type == 'therapy' and event.title != FREE_SESSION_TITLE
            purchase_used = event.purchase_used # Obtener la FK (puede ser None)

            if is_refundable_type:
                now = timezone.now()
                event_start_time = event.start_time
                cancelation_window = timedelta(hours=CANCELATION_POLICY_HOURS)

                # Comprobar si la cancelación es con suficiente antelación
                if event_start_time > now + cancelation_window:
                    logger.info(f"Cancelación de evento {event_id} dentro de la ventana ({CANCELATION_POLICY_HOURS}h). Intentando devolver sesión.")

                    # INTENTO 1: Usar la referencia directa si se guardó
                    if purchase_used:
                        try:
                            # Verificar que la compra aún existe y está completada
                            purchase_to_refund = Purchase.objects.get(id=purchase_used.id, payment_status='completed')
                            purchase_to_refund.remaining_sessions += 1
                            purchase_to_refund.save(update_fields=['remaining_sessions'])
                            session_returned = True
                            purchase_refunded_id = purchase_to_refund.id
                            message = f'Sesión cancelada con éxito con más de {CANCELATION_POLICY_HOURS} horas de antelación. Se ha devuelto 1 sesión a tu cuenta (Compra ID: {purchase_refunded_id}).'
                            logger.info(f"Sesión devuelta a compra específica ID {purchase_refunded_id}. Restantes: {purchase_to_refund.remaining_sessions}")
                        except Purchase.DoesNotExist:
                             logger.error(f"Error al devolver sesión para evento {event_id}: La compra referenciada (ID: {purchase_used.id}) no existe o no está completada.")
                             message = 'Sesión cancelada. Hubo un problema al intentar devolver la sesión (referencia de compra inválida). Contacta a soporte.'
                        except Exception as e_refund:
                             logger.error(f"Error inesperado al devolver sesión a compra {purchase_used.id} para evento {event_id}: {e_refund}", exc_info=True)
                             message = 'Sesión cancelada. Hubo un error interno al devolver la sesión a tu cuenta. Contacta a soporte.'

                    # INTENTO 2: Fallback si no se guardó la referencia (MENOS PRECISO)
                    else:
                        logger.warning(f"No se encontró referencia 'purchase_used' en evento {event_id}. Intentando encontrar compra compatible para reembolso (fallback).")
                        purchase_to_refund = None
                        # Buscar compra compatible basada en si el evento tenía terapia o no
                        if event.terapia: # Era sesión de terapia específica
                             purchase_query = Purchase.objects.filter(
                                 terapia=event.terapia,
                                 payment_status='completed',
                                 # therapy_type_purchased=event.terapia.tipo # Opcional: ser más estricto
                             ).order_by('-purchase_date') # Devolver a la más reciente?
                        else: # Era sesión individual genérica
                             purchase_query = Purchase.objects.filter(
                                 user=user,
                                 terapia__isnull=True,
                                 therapy_type_purchased='individual',
                                 payment_status='completed',
                             ).order_by('-purchase_date')

                        compatible_purchase = purchase_query.first()

                        if compatible_purchase:
                             compatible_purchase.remaining_sessions += 1
                             compatible_purchase.save(update_fields=['remaining_sessions'])
                             session_returned = True
                             purchase_refunded_id = compatible_purchase.id
                             message = f'Sesión cancelada con éxito con más de {CANCELATION_POLICY_HOURS} horas de antelación. Se ha devuelto 1 sesión a una compra compatible (ID: {purchase_refunded_id}).'
                             logger.info(f"Sesión devuelta a compra compatible (fallback) ID {purchase_refunded_id}. Restantes: {compatible_purchase.remaining_sessions}")
                        else:
                             message = 'Sesión cancelada a tiempo, pero no se encontró una compra compatible para devolver la sesión. Contacta a soporte.'
                             logger.error(f"Error al devolver sesión (fallback) para evento {event_id}: No se encontró compra compatible.")

                else: # Cancelación tardía
                    message = f'Cancelación realizada con menos de {CANCELATION_POLICY_HOURS} horas de antelación o la sesión ya pasó. No se devuelve el crédito.'
                    logger.info(f"Cancelación tardía o pasada de evento {event_id}. No se devuelve sesión.")
            # --- Fin Lógica Devolución Crédito ---

            # --- Enviar correos de cancelación (si es terapia) ---
            if event.type == 'therapy':
                try:
                   # Reutilizar lógica de correos de actualización/creación con plantilla/asunto de cancelación
                   user_name = event.user.nombre or event.user.email.split('@')[0]
                   psychologist_name = event.psychologist.nombre or event.psychologist.email.split('@')[0]
                   is_free_session_event = event.title == FREE_SESSION_TITLE
                   session_type_str = 'Gratuita' if is_free_session_event else 'Regular'

                   base_context = { # Contexto con datos del evento cancelado
                       'session_date': event.start_time.strftime('%Y-%m-%d'),
                       'session_time': event.start_time.strftime('%H:%M %Z'),
                       'session_type': session_type_str,
                       'terapia_id': event.terapia.id if event.terapia else None,
                       'terapia_display': event.terapia.get_tipo_display() if event.terapia else 'Individual (Genérica)',
                       'year': timezone.now().year,
                       'support_contact': getattr(settings, 'SUPPORT_EMAIL', 'soporte@senti.lat'),
                       'platform_name': getattr(settings, 'PLATFORM_NAME', 'Senti'),
                       'cancellation_reason': message # Incluir el mensaje sobre el reembolso/no reembolso
                   }
                   # Enviar correo al paciente
                   patient_context = base_context.copy()
                   patient_context.update({'nombre': user_name, 'psychologist_name': psychologist_name, 'dashboard_url': '...'})
                   send_brevo_email(subject=f"Cancelación de tu Sesión de Terapia {session_type_str}", to_email=event.user.email, template_name="therapy_cancellation_email.html", context=patient_context)
                   logger.info(f"Correo de cancelación de paciente enviado a {event.user.email} para evento {event_id}")

                   # Enviar correo a la psicóloga
                   psychologist_context = base_context.copy()
                   psychologist_context.update({'psychologist_name': psychologist_name, 'patient_name': user_name, 'dashboard_url': '...'})
                   send_brevo_email(subject=f"Sesión {session_type_str} Cancelada por {user_name}", to_email=event.psychologist.email, template_name="psychologist_session_cancellation.html", context=psychologist_context)
                   logger.info(f"Correo de cancelación a psicóloga enviado a {event.psychologist.email} para evento {event_id}")

                except Exception as e:
                    logger.error(f"Error al enviar correos de cancelación para evento {event_id}: {str(e)}", exc_info=True)

            # --- Eliminar el Evento ---
            event_title_deleted = event.title
            event_type_deleted = event.type
            event.delete()
            logger.info(f"Evento eliminado: {event_id} (Título: {event_title_deleted}, Tipo: {event_type_deleted}) por usuario {user.username}")

            # --- Preparar Respuesta Exitosa ---
            return Response({
                'message': message,
                'session_returned': session_returned,
                'purchase_refunded_id': purchase_refunded_id
            }, status=status.HTTP_200_OK) # OK incluso si no se devuelve sesión

        except CalendarEvent.DoesNotExist:
             logger.warning(f"Intento de eliminar evento no existente o no autorizado: {event_id} por usuario {user.username}")
             return Response({'error': 'Evento no encontrado o no tienes permiso para eliminarlo'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error inesperado en CalendarEventDeleteView para evento {event_id}: {str(e)}", exc_info=True)
            return Response({'error': 'Error interno del servidor al eliminar el evento'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CalendarEventJitsiLinkView(APIView):
    """
    Proporciona el enlace de Jitsi Meet para un evento de terapia específico.
    Accesible por el paciente o la psicóloga asignada al evento.
    El enlace solo se genera/devuelve poco antes de la sesión y el mismo día.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        user = request.user
        logger.debug(f"Usuario {user.email} solicitando enlace Jitsi para evento {event_id}")

        try:
            # Buscar el evento permitiendo acceso si es el paciente O la psicóloga
            event = get_object_or_404(
                CalendarEvent,
                Q(event_id=event_id),
                Q(type='therapy'), # Solo para eventos de terapia
                Q(user=user) | Q(psychologist=user) # Usuario es paciente O psicólogo
            )

            now = timezone.now()

            # --- Validaciones de Tiempo ---
            if event.start_time.date() != now.date():
                logger.info(f"Acceso a enlace Jitsi denegado para {event_id}: No es el día de la sesión.")
                return Response(
                    {'error': 'El enlace de la videollamada solo está disponible el día de la sesión.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Permitir acceso un poco antes (ej. 10 minutos)
            if now < event.start_time - timedelta(minutes=10):
                 logger.info(f"Acceso a enlace Jitsi denegado para {event_id}: Aún es muy temprano.")
                 # Calcular cuántos minutos faltan
                 time_to_session = event.start_time - now
                 minutes_to_wait = int(time_to_session.total_seconds() / 60) - 10
                 return Response(
                     {'error': f'El enlace estará disponible 10 minutos antes de la sesión (en aprox. {max(0, minutes_to_wait)} minutos).'},
                     status=status.HTTP_403_FORBIDDEN
                 )
             # Podrías añadir una ventana de tiempo *después* de la sesión donde el enlace ya no es válido
             # if now > event.end_time + timedelta(minutes=30):
             #    return Response({'error': 'La sesión ya ha finalizado.'}, status=status.HTTP_403_FORBIDDEN)
            # --- Fin Validaciones de Tiempo ---


            # Generar o devolver el enlace existente
            # generate_jitsi_meet_link debería ser idempotente o verificar si ya existe
            jitsi_meet_link = event.jitsi_meet_link or event.generate_jitsi_meet_link()
            logger.info(f"Enlace Jitsi devuelto para evento {event_id} a usuario {user.email}: {jitsi_meet_link}")

            # --- Preparar Respuesta Exitosa ---
            response_data = {
                'event_id': event.event_id,
                'jitsi_meet_link': jitsi_meet_link,
                'start_time': event.start_time.isoformat(),
                'end_time': event.end_time.isoformat(),
                'title': event.title,
            }
            # Añadir info relevante según el rol
            if user == event.psychologist:
                response_data['patient'] = {
                    'id': event.user.id,
                    'nombre': event.user.nombre or event.user.email.split('@')[0],
                }
            elif user == event.user:
                 response_data['psychologist'] = {
                    'id': event.psychologist.id,
                    'nombre': event.psychologist.nombre or event.psychologist.email.split('@')[0],
                 }

            return Response(response_data, status=status.HTTP_200_OK)

        except CalendarEvent.DoesNotExist:
            logger.warning(f"Evento {event_id} no encontrado o acceso denegado para {user.email} al solicitar enlace Jitsi.")
            return Response(
                {'error': 'Evento no encontrado o no tienes acceso a este enlace'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error inesperado en CalendarEventJitsiLinkView para evento {event_id}: {str(e)}", exc_info=True)
            return Response({'error': 'Error interno del servidor al obtener el enlace'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
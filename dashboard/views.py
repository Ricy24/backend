from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.utils import timezone
from datetime import date, timedelta
from google_calendar.models import CalendarEvent
from .models import Mood, SupportGroup, PsychologicalTest, DiaryEntry, DiaryConversation, SleepLog, UserStreak
from api.models import Usuario, Terapia, MiembroTerapia
from rest_framework.decorators import api_view, permission_classes
import logging
from django.conf import settings
from groq import Groq
import re
import calendar
import whisper
import logging
import tempfile
import os
from django.shortcuts import get_object_or_404

import threading
from django.db.models import Count
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

logger = logging.getLogger(__name__)

  # --- Carga del Modelo Whisper ---
  # Puedes definir el tamaño en settings.py o aquí directamente
WHISPER_MODEL_SIZE = getattr(settings, 'WHISPER_MODEL_SIZE', 'base')

# --- Variable global para almacenar el modelo una vez cargado (dentro de cada proceso) ---
_whisper_model_instance = None
_whisper_model_load_lock = threading.Lock() # Para evitar race conditions si múltiples hilos intentan cargar




# --- FUNCIÓN PARA OBTENER/CARGAR EL MODELO ---
def get_whisper_model():
    """
    Obtiene la instancia global del modelo Whisper, cargándola si es necesario.
    Esta función es segura para hilos (thread-safe).
    """
    global _whisper_model_instance
    # Doble verificación para eficiencia (evita adquirir el lock innecesariamente)
    if _whisper_model_instance is None:
        with _whisper_model_load_lock:
            # Segunda verificación dentro del lock por si otro hilo ya lo cargó mientras esperábamos
            if _whisper_model_instance is None:
                logger.info(f"Iniciando carga del modelo Whisper ({WHISPER_MODEL_SIZE})...")
                try:
                    # Carga real del modelo
                    _whisper_model_instance = whisper.load_model(WHISPER_MODEL_SIZE)
                    logger.info(f"Modelo Whisper '{WHISPER_MODEL_SIZE}' cargado exitosamente en este proceso.")
                except MemoryError as me:
                    logger.error(f"¡MemoryError! No hay suficiente memoria para cargar el modelo Whisper '{WHISPER_MODEL_SIZE}'. {me}")
                    # Mantener _whisper_model_instance como None
                    _whisper_model_instance = None # Asegurarse que quede None
                    # Podrías lanzar una excepción específica o simplemente devolver None
                    # raise me # Relanzar si quieres que el error se propague inmediatamente
                except Exception as e:
                    logger.error(f"Error crítico durante la carga del modelo Whisper ({WHISPER_MODEL_SIZE}): {e}", exc_info=True)
                    _whisper_model_instance = None # Asegurar que quede None si falla
                    # raise e # Relanzar si quieres que el error se propague

    # Devolver la instancia (puede ser None si la carga falló)
    return _whisper_model_instance


# Inicializar Groq con la API key desde settings
groq_client = Groq(api_key=settings.GROQ_API_KEY)

# Función auxiliar para calcular días de bienestar
def calculate_wellness_days(user):
    moods = Mood.objects.filter(user=user).order_by('-timestamp')[:7]
    positive_moods = sum(1 for mood in moods if mood.mood in ['Bien', 'Excelente'])
    return positive_moods

# Función para sanitizar el contenido y prevenir inyección de prompts
def sanitize_content(content):
    dangerous_patterns = [
        r'```.*```',
        r'<\s*script.*?>.*?</\s*script\s*>',
        r'(system|admin|root|eval|exec|import|os|sys)',
        r'http[s]?://',
    ]
    sanitized = content
    for pattern in dangerous_patterns:
        sanitized = re.sub(pattern, '[CONTENIDO ELIMINADO]', sanitized, flags=re.IGNORECASE | re.DOTALL)
    return sanitized

# Vista para obtener datos del dashboard
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_data(request):
    try:
        user = request.user
        next_appointment = CalendarEvent.objects.filter(
            user=user, 
            start_time__gte=timezone.now()
        ).order_by('start_time').first()
        latest_mood = Mood.objects.filter(user=user).order_by('-timestamp').first()
        mood_history = [
            {'mood': mood.mood, 'date': mood.timestamp.isoformat()}
            for mood in Mood.objects.filter(user=user).order_by('-timestamp')[:7]
        ]
        diary_entries = [
            {'title': entry.title or 'Sin título', 'date': entry.date.isoformat()}
            for entry in DiaryEntry.objects.filter(user=user).order_by('-date')[:5]
        ]
        sleep_logs = [
            {'hours_slept': log.hours_slept, 'date': log.date.isoformat()}
            for log in SleepLog.objects.filter(user=user).order_by('-date')[:7]
        ]
        stats = {
            'nextAppointment': {
                'date': next_appointment.start_time.date().isoformat() if next_appointment else '',
                'type': next_appointment.type if next_appointment else ''
            },
            'wellnessDays': calculate_wellness_days(user),
            'completedSessions': CalendarEvent.objects.filter(
                user=user, 
                end_time__lt=timezone.now()
            ).count(),
            'mood': latest_mood.mood if latest_mood else 'No registrado',
            'averageSleep': sum(log['hours_slept'] for log in sleep_logs) / len(sleep_logs) if sleep_logs else 0,
        }
        upcoming_activities = [
            {
                'title': event.title,
                'time': event.start_time.strftime('%Y-%m-%d %H:%M'),
                'duration': str(int((event.end_time - event.start_time).total_seconds() / 3600)) + 'h',
                'color': 'from-blue-500-to-cyan-600',
                'icon': 'Calendar'
            }
            for event in CalendarEvent.objects.filter(user=user, start_time__gte=timezone.now())
        ] + [
            {
                'title': group.name,
                'time': group.time.strftime('%Y-%m-%d %H:%M'),
                'duration': group.duration,
                'color': 'from-purple-500-to-indigo-600',
                'icon': 'Users'
            }
            for group in SupportGroup.objects.filter(users=user, time__gte=timezone.now())
        ]
        tests = [
            {
                'name': test.name,
                'score': test.score,
                'completed_at': test.completed_at.isoformat()
            }
            for test in PsychologicalTest.objects.filter(user=user)
        ]
        response_data = {
            'stats': stats,
            'upcomingActivities': upcoming_activities,
            'psychologicalTests': tests,
            'moodHistory': mood_history,
            'diaryEntries': diary_entries,
            'sleepLogs': sleep_logs,
        }
        logger.debug(f"Datos del dashboard devueltos: {response_data}")
        return Response(response_data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error en dashboard_data: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Vista para actualizar el estado de ánimo
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_mood(request):
    try:
        user = request.user
        mood = request.data.get('mood')
        description = request.data.get('description', '')
        
        if not mood:
            return Response({'error': 'El estado de ánimo es obligatorio'}, status=status.HTTP_400_BAD_REQUEST)
        
        if mood not in ['Excelente', 'Bien', 'Regular', 'Necesito Ayuda']:
            return Response({'error': 'Estado de ánimo inválido'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Usar la fecha local para el timestamp
        local_timestamp = timezone.localtime(timezone.now())
        
        mood_obj = Mood.objects.create(
            user=user,
            mood=mood,
            description=description,
            timestamp=local_timestamp
        )
        
        wellness_days = calculate_wellness_days(user)
        
        return Response({
            'mood': mood_obj.mood,
            'description': mood_obj.description,
            'date': mood_obj.timestamp.isoformat(),
            'wellnessDays': wellness_days,
            'message': 'Estado de ánimo actualizado'
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.error(f"Error en update_mood: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Vista para registrar el sueño
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def log_sleep(request):
    try:
        user = request.user
        hours_slept = request.data.get('hours_slept')
        date_str = request.data.get('date', timezone.localtime(timezone.now()).date().isoformat())
        
        if hours_slept is None:
            return Response({'error': 'Las horas dormidas son obligatorias'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            hours_slept = float(hours_slept)
            if hours_slept < 0 or hours_slept > 24:
                return Response({'error': 'Las horas dormidas deben estar entre 0 y 24'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({'error': 'Las horas dormidas deben ser un número válido'}, status=status.HTTP_400_BAD_REQUEST)
        
        from datetime import datetime
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        if hours_slept >= 7 and hours_slept <= 9:
            sleep_quality = 'Bueno'
            color = '#22c55e'
        elif hours_slept >= 5 and hours_slept < 7:
            sleep_quality = 'Intermedio'
            color = '#f59e0b'
        else:
            sleep_quality = 'Malo'
            color = '#ef4444'

        sleep_log, created = SleepLog.objects.update_or_create(
            user=user,
            date=date_obj,
            defaults={
                'hours_slept': hours_slept,
                'sleep_quality': sleep_quality
            }
        )
        
        return Response({
            'hours_slept': sleep_log.hours_slept,
            'date': sleep_log.date.isoformat(),
            'sleep_quality': sleep_log.sleep_quality,
            'color': color,
            'message': 'Sueño registrado' if created else 'Sueño actualizado'
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error en log_sleep: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def update_user_streak(user, entry_date):
    streak, created = UserStreak.objects.get_or_create(user=user, defaults={'current_streak': 0, 'last_entry_date': None})
    
    if streak.last_entry_date is None:
        streak.current_streak = 1
        streak.last_entry_date = entry_date
    else:
        delta = (entry_date - streak.last_entry_date).days
        if delta == 1:
            streak.current_streak += 1
        elif delta > 1:
            streak.current_streak = 1
        streak.last_entry_date = entry_date
    
    streak.save()
    return streak.current_streak

def create_empty_entry_if_needed(user, check_date):
    if not DiaryEntry.objects.filter(user=user, date=check_date).exists():
        day_name = calendar.day_name[check_date.weekday()]
        DiaryEntry.objects.create(
            user=user,
            date=check_date,
            day_name=day_name,
            title="Sin título",
            content="😔 Abandonaste tu diario hoy",
            is_empty=True
        )
        streak, created = UserStreak.objects.get_or_create(user=user, defaults={'current_streak': 0, 'last_entry_date': None})
        if streak.current_streak > 0 and (check_date - streak.last_entry_date).days > 1:
            streak.current_streak = 0
            streak.last_entry_date = check_date
            streak.save()

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_diary_entry(request):
    try:
        user = request.user
        title = request.data.get('title', '')
        content = request.data.get('content', '')
        emotion = request.data.get('emotion', '')
        terapia_id = request.data.get('terapia_id') # <-- OBTENER TERAPIA ID
        today = timezone.localtime(timezone.now()).date()
        day_name = calendar.day_name[today.weekday()]

        # --- VALIDACIÓN DE TERAPIA ---
        if not terapia_id:
            return Response({'error': 'Se requiere el ID de la terapia.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            tid = int(terapia_id)
            terapia = get_object_or_404(Terapia, id=tid)
            # Verificar membresía
            if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                return Response(
                    {'error': 'No eres miembro de esta terapia.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        except (ValueError, TypeError):
             return Response({'error': 'ID de terapia inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        except Terapia.DoesNotExist:
             return Response({'error': f'Terapia con ID {terapia_id} no encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        # --- FIN VALIDACIÓN TERAPIA ---

        if emotion not in [choice[0] for choice in DiaryEntry._meta.get_field('emotion').choices]:
            return Response({'error': 'Emoción no válida'}, status=status.HTTP_400_BAD_REQUEST)

        # --- Verificar si ya existe una entrada para hoy en esta terapia ---
        existing_entry = DiaryEntry.objects.filter(user=user, terapia=terapia, date=today).first()
        if existing_entry:
             # Puedes decidir si actualizar o devolver error. Actualizar parece más útil.
             existing_entry.title = title or "Sin título"
             existing_entry.content = content
             existing_entry.is_empty = not content.strip()
             existing_entry.emotion = emotion
             existing_entry.day_name = day_name # Actualizar por si acaso
             existing_entry.save()
             entry = existing_entry
             status_code = status.HTTP_200_OK
             message = 'Entrada de diario actualizada'
        else:
            # --- CREAR LA NUEVA ENTRADA CON TERAPIA ---
            entry = DiaryEntry.objects.create(
                user=user,
                terapia=terapia, # <-- GUARDAR TERAPIA
                date=today,
                day_name=day_name,
                title=title or "Sin título",
                content=content,
                is_empty=not content.strip(),
                emotion=emotion
            )
            status_code = status.HTTP_201_CREATED
            message = 'Entrada de diario creada'

        current_streak = update_user_streak(user, today) # Asumiendo que update_user_streak existe

        return Response({
            'id': entry.id,
            'title': entry.title,
            'content': entry.content,
            'date': entry.date.isoformat(),
            'day_name': entry.day_name,
            'is_empty': entry.is_empty,
            'emotion': entry.emotion,
            'terapia_id': entry.terapia.id if entry.terapia else None, # <-- Devolver ID terapia
            'current_streak': current_streak,
            'message': message
        }, status=status_code) # <-- Usar status_code dinámico

    except Exception as e:
        logger.error(f"Error en create_diary_entry: {str(e)}", exc_info=True)
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def diary_entries(request):
    try:
        user = request.user
        today = timezone.localtime(timezone.now()).date()
        start_date = user.date_joined.date()  # Asumiendo que `date_joined` es el equivalente a `fecha_registro`
        entries = DiaryEntry.objects.filter(user=user).order_by('-date')

        # Agrupar entradas por día y calcular emoción dominante
        entries_by_date = {}
        for entry in entries:
            date_str = entry.date.isoformat()
            if date_str not in entries_by_date:
                entries_by_date[date_str] = []
            entries_by_date[date_str].append(entry)

        response_entries = []
        calendar_data = []
        for entry_date in sorted(entries_by_date.keys(), reverse=True):
            day_entries = entries_by_date[entry_date]
            emotions = [entry.emotion for entry in day_entries if entry.emotion]
            dominant_emotion = max(set(emotions), key=emotions.count, default=None) if emotions else None

            response_entries.append({
                'date': entry_date,
                'dominant_emotion': dominant_emotion,
                'entries': [
                    {
                        'id': entry.id,
                        'title': entry.title,
                        'content': entry.content,
                        'day_name': entry.day_name,
                        'is_empty': entry.is_empty,
                        'emotion': entry.emotion,
                        'conversations': [
                            {
                                'role': conv.role,
                                'content': conv.content,
                                'timestamp': conv.timestamp.isoformat()
                            }
                            for conv in entry.conversations.all().order_by('timestamp')
                        ]
                    }
                    for entry in day_entries
                ]
            })

        check_date = start_date
        while check_date <= today:
            date_str = check_date.isoformat()
            has_entry = any(entry.date == check_date and not entry.is_empty for entry in entries)
            calendar_data.append({
                'date': date_str,
                'has_entry': has_entry,
                'is_empty': not has_entry and any(entry.date == check_date for entry in entries)
            })
            check_date += timedelta(days=1)

        streak = UserStreak.objects.get_or_create(user=user, defaults={'current_streak': 0, 'last_entry_date': None})[0]

        return Response({
            'entries': response_entries,
            'current_streak': streak.current_streak,
            'calendar': calendar_data
        }, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error en diary_entries: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def talk_about_entry(request):
    try:
        user = request.user
        entry_id = request.data.get('entry_id')
        user_message = request.data.get('message', '')

        if not entry_id:
            return Response({'error': 'Se requiere el ID de la entrada'}, status=status.HTTP_400_BAD_REQUEST)
        
        entry = DiaryEntry.objects.filter(user=user, id=entry_id).first()
        if not entry:
            return Response({'error': 'Entrada no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        
        today = timezone.localtime(timezone.now()).date()
        conversation_count = DiaryConversation.objects.filter(
            diary_entry__user=user,
            diary_entry__date=today,
            role='assistant',
            timestamp__date=today
        ).count()
        if conversation_count >= 5:
            return Response({'error': 'Límite de 5 conversaciones por día alcanzado'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        if user_message:
            DiaryConversation.objects.create(
                diary_entry=entry,
                role='user',
                content=user_message
            )
        
        system_prompt = (
            f"Eres un asistente actuando como un amigo cercano y un psicólogo empático. El usuario escribió lo siguiente en su diario el {entry.date.strftime('%d/%m/%Y')} ({entry.day_name}): \"{entry.content}\". "
            f"Además, etiquetó esta entrada como '{entry.get_emotion_display()}'. "
            "Responde de manera cálida, comprensiva y de apoyo, invitando al usuario a reflexionar más sobre ese día o a compartir cómo se siente ahora. "
            "Usa un tono conversacional, natural y evita cualquier juicio. Haz preguntas abiertas o comentarios que fomenten la introspección."
        )
        user_prompt = user_message if user_message else "Hola, quiero hablar de este día."
        
        response = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=200,
            temperature=0.7
        )
        assistant_message = response.choices[0].message.content.strip()
        
        DiaryConversation.objects.create(
            diary_entry=entry,
            role='assistant',
            content=assistant_message
        )
        
        return Response({
            'entry_id': entry_id,
            'message': assistant_message
        }, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error en talk_about_entry: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_day_pdf(request, date_str):
    try:
        user = request.user
        try:
            export_date = date.fromisoformat(date_str)
        except ValueError:
            return Response({'error': 'Formato de fecha inválido'}, status=status.HTTP_400_BAD_REQUEST)

        entries = DiaryEntry.objects.filter(user=user, date=export_date).order_by('id')
        if not entries:
            return Response({'error': 'No hay entradas para esta fecha'}, status=status.HTTP_404_NOT_FOUND)

        emotions = [entry.emotion for entry in entries if entry.emotion]
        dominant_emotion = max(set(emotions), key=emotions.count, default=None) if emotions else None
        dominant_emotion_display = next((choice[1] for choice in DiaryEntry._meta.get_field('emotion').choices if choice[0] == dominant_emotion), None) if dominant_emotion else 'Sin emoción dominante'

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="diario-{date_str}.pdf"'

        doc = SimpleDocTemplate(response, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph(f"Diario - {export_date.strftime('%d/%m/%Y')}", styles['Title']))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"Emoción dominante del día: {dominant_emotion_display}", styles['Heading2']))
        elements.append(Spacer(1, 12))

        for entry in entries:
            elements.append(Paragraph(entry.title or "Sin título", styles['Heading3']))
            elements.append(Paragraph(f"Emoción: {entry.get_emotion_display()}", styles['Italic']))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(entry.content, styles['BodyText']))
            elements.append(Spacer(1, 12))

            if entry.conversations.exists():
                elements.append(Paragraph("Conversación con la IA:", styles['Heading4']))
                conversation_data = []
                for conv in entry.conversations.all().order_by('timestamp'):
                    role = "Tú" if conv.role == 'user' else "Asistente"
                    conversation_data.append([role, conv.content])
                
                table = Table(conversation_data)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ]))
                elements.append(table)
                elements.append(Spacer(1, 12))

        doc.build(elements)
        return response
    except Exception as e:
        logger.error(f"Error en export_day_pdf: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
# --- Nueva Vista para Transcripción ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def transcribe_audio_view(request):
      # Intenta obtener el modelo usando la función lazy loader
      try:
          model = get_whisper_model()
      except MemoryError: # Capturar si get_whisper_model relanza MemoryError
          logger.error("Fallo en transcripción debido a MemoryError al cargar modelo.")
          return Response(
              {'error': 'Servicio no disponible temporalmente debido a recursos limitados.'},
              status=status.HTTP_503_SERVICE_UNAVAILABLE
          )
      except Exception as load_err: # Capturar otros errores de carga si get_whisper_model los relanza
          logger.error(f"Fallo en transcripción debido a error al cargar modelo: {load_err}", exc_info=True)
          return Response(
              {'error': 'Error interno al inicializar el servicio de transcripción.'},
              status=status.HTTP_500_INTERNAL_SERVER_ERROR
          )


      # Verifica si el modelo se cargó correctamente (si get_whisper_model devuelve None)
      if model is None:
          logger.error("Intento de transcripción fallido: El modelo Whisper no pudo ser cargado (probablemente MemoryError anterior).")
          # El log dentro de get_whisper_model debería haber detallado el error.
          return Response(
              {'error': 'Servicio de transcripción no disponible temporalmente (error de inicialización).'},
              status=status.HTTP_503_SERVICE_UNAVAILABLE
          )

      # --- Resto de tu lógica de transcripción (sin cambios) ---
      if 'audio' not in request.FILES:
          return Response(
              {'error': 'No se encontró archivo de audio en la solicitud.'},
              status=status.HTTP_400_BAD_REQUEST
          )

      audio_file = request.FILES['audio']
      logger.info(f"Recibido archivo de audio: {audio_file.name}, tamaño: {audio_file.size} bytes")

      temp_audio_path = None # Definir fuera del try para el finally
      try:
          # Usar un archivo temporal seguro
          # Necesitamos importar threading al principio del archivo
          import threading
          with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio_file:
              for chunk in audio_file.chunks():
                  temp_audio_file.write(chunk)
              temp_audio_path = temp_audio_file.name
          
          logger.info(f"Archivo temporal creado en: {temp_audio_path}")

          # Transcribir usando Whisper
          logger.info("Iniciando transcripción con Whisper...")
          # Usar la instancia 'model' obtenida de get_whisper_model()
          result = model.transcribe(temp_audio_path, language="es", fp16=False)
          transcript = result['text']
          logger.info("Transcripción completada.")

          return Response({'transcript': transcript}, status=status.HTTP_200_OK)

      except Exception as e:
          logger.error(f"Error durante la transcripción: {e}", exc_info=True)
          return Response(
              {'error': f'Error al procesar el audio: {str(e)}'},
              status=status.HTTP_500_INTERNAL_SERVER_ERROR
          )
      finally:
          # Asegurarse de limpiar el archivo temporal si se creó
          if temp_audio_path and os.path.exists(temp_audio_path):
              try:
                  os.remove(temp_audio_path)
                  logger.info(f"Archivo temporal eliminado: {temp_audio_path}")
              except OSError as rm_err:
                  logger.error(f"Error al eliminar archivo temporal: {rm_err}")
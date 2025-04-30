from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q, F
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import random
from rest_framework.permissions import IsAuthenticated
# Importar parsers para manejar archivos
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from dashboard.models import DiaryEntry

from .models import (
    InitialScreeningAssessment, EmotionalProfile, Category,
    EmotionalPath, Challenge, UserChallenge, UserPathProgress, DailyComponent
)
from .serializers import (
    InitialScreeningAssessmentSerializer, CategorySerializer,
    EmotionalPathSerializer, ChallengeSerializer, UserChallengeSerializer,
    UserPathProgressSerializer, DailyComponentSerializer
)
from api.models import Terapia, MiembroTerapia
# Assuming your User model is accessible this way or adjust import
from django.contrib.auth import get_user_model
User = get_user_model()
from django.utils import timezone
from chat.models import Mensaje
import logging
from datetime import date, timedelta, time

# Importar el modelo Plant desde la aplicación plant
from plant.models import Plant
from django.db import transaction

# Importar utilidades para R2
from .utils.r2_storage import upload_file_to_r2, generate_unique_object_name
from django.conf import settings # Necesario para acceder al nombre del bucket
import os # Necesario para path.splitext si se usa en generate_unique_object_name
from rest_framework.pagination import PageNumberPagination
logger = logging.getLogger(__name__)

# Definición de las preguntas (sin cambios)
QUESTIONS = {
    1: {
        "text": "¿Con qué frecuencia te sientes abrumado por preocupaciones que no puedes control?",
        "categories": {"Ansiedad": 3, "Estrés": 2, "Manejo emocional": 1}
    },
    2: {
        "text": "¿Sientes que tu confianza en ti mismo afecta tus decisiones o relaciones diarias?",
        "categories": {"Autoestima": 3, "Habilidades sociales": 2, "Relaciones de pareja": 1}
    },
    3: {
        "text": "¿Con qué frecuencia te sientes atrapado en pensamientos negativos o rumiaciones?",
        "categories": {"Depresión": 3, "Ansiedad": 2, "Trauma": 1}
    },
    4: {
        "text": "¿Tienes dificultades para dormir o descansar adecuadamente por razones emocionales o mentales?",
        "categories": {"Estrés": 3, "Problemas de sueño": 3, "Ansiedad": 1}
    },
    5: {
        "text": "¿Te resulta difícil manejar tus emociones intensas como la ira, tristeza o frustración?",
        "categories": {"Manejo emocional": 3, "Impulsividad": 2, "Autoestima": 1}
    },
    6: {
        "text": "¿Sientes que has perdido motivación o propósito en tu vida reciente?",
        "categories": {"Motivación": 3, "Depresión": 2, "Crisis existencial": 1}
    },
    7: {
        "text": "¿Tienes problemas para comunicarte abiertamente con personas cercanas a ti?",
        "categories": {"Comunicación": 3, "Relaciones de pareja": 2, "Familia y crianza": 1}
    },
    8: {
        "text": "¿Evitas situaciones sociales o sientes incomodidad al interactuar con los demás?",
        "categories": {"Habilidades sociales": 3, "Ansiedad": 2, "Autoestima": 1}
    },
    9: {
        "text": "¿Sientes que cargas con heridas emocionales del pasado que afectan tu presente?",
        "categories": {"Trauma": 3, "Reencuentro con uno mismo": 2, "Depresión": 1}
    },
    10: {
        "text": "¿Te cuesta adaptarte a los cambios o sientes miedo ante lo nuevo?",
        "categories": {"Manejo del cambio": 3, "Ansiedad": 2, "Impulsividad": 1}
    },
    11: {
        "text": "¿Tienes pensamientos autocríticos o te juzgas constantemente?",
        "categories": {"Autoestima": 3, "Depresión": 2, "Prevención del suicidio": 1}
    },
    12: {
        "text": "¿Tienes conflictos recurrentes con tu familia o sientes tensión en casa?",
        "categories": {"Familia y crianza": 3, "Manejo emocional": 2, "Comunicación": 1}
    },
    13: {
        "text": "¿Tienes dificultades para disfrutar de actividades que antes te gustaban?",
        "categories": {"Depresión": 3, "Motivación": 2, "Estrés": 1}
    },
    14: {
        "text": "¿Sientes que no te entiendes a ti mismo o que has perdido tu identidad?",
        "categories": {"Identidad": 3, "Reencuentro con uno mismo": 2, "Crisis existencial": 1}
    },
    15: {
        "text": "¿Te cuesta mantener hábitos saludables como alimentación, sueño o ejercicio?",
        "categories": {"Trastornos de alimentación": 3, "Impulsividad": 2, "Estrés": 1}
    }
}

class InitialScreeningAssessmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Devuelve las preguntas del test inicial si no está completado.
        """
        try:
            terapia_id = request.query_params.get('terapia_id')
            therapy_type = request.query_params.get('therapy_type', 'individual')

            if not terapia_id:
                return Response(
                    {"error": "Se requiere el ID de la terapia."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            terapia = get_object_or_404(Terapia, id=terapia_id)
            if not MiembroTerapia.objects.filter(terapia=terapia, usuario=request.user).exists():
                return Response(
                    {"error": "No eres miembro de esta terapia."},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Verificar si ya se completó
            if InitialScreeningAssessment.objects.filter(
                user=request.user, terapia=terapia, therapy_type=therapy_type
            ).exists():
                return Response(
                    {"error": "Ya completaste esta evaluación."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Generar preguntas
            questions = [
                {
                    'question_id': q_id,
                    'text': info['text'],
                    'categories': list(info['categories'].keys())
                }
                for q_id, info in QUESTIONS.items()
            ]

            # Ajustar preguntas según tipo de terapia
            if therapy_type == 'couple':
                questions[5]['text'] = "¿Te cuesta conectar emocionalmente con tu pareja?"
            elif therapy_type == 'family':
                questions[11]['text'] = "¿Sientes que las dinámicas familiares generan tensión en el hogar?"

            logger.info(f"Preguntas enviadas a {request.user.email} ({therapy_type})")
            return Response({'questions': questions}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al obtener preguntas: {str(e)}", exc_info=True)
            return Response(
                {'error': 'No se pudieron obtener las preguntas.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request):
        """
        Procesa el envío del test inicial.
        """
        serializer = InitialScreeningAssessmentSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            logger.warning(f"Falló la validación para {request.user.email}: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            assessment = serializer.save()
            logger.info(f"Evaluación completada por {request.user.email}")
            return Response(
                {
                    'message': 'Evaluación completada exitosamente.',
                    'assessment_id': assessment.id,
                    # Asegurarse de que el perfil exista antes de intentar acceder a scores
                    'profile': assessment.user.emotional_profiles.filter(terapia=assessment.terapia).first().scores
                },
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            logger.error(f"Error al procesar evaluación: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Error interno al procesar la evaluación.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class EmotionalPathView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Obtiene las rutas emocionales activas del usuario.
        """
        try:
            terapia_id = request.query_params.get('terapia_id')
            user = request.user
            paths = EmotionalPath.objects.filter(user=user, is_active=True)
            if terapia_id:
                try:
                    # Validar que terapia_id sea un entero
                    tid = int(terapia_id)
                    paths = paths.filter(terapia_id=tid)
                except (ValueError, TypeError):
                     return Response(
                         {'error': 'El ID de la terapia debe ser un número válido.'},
                         status=status.HTTP_400_BAD_REQUEST
                     )
                except Terapia.DoesNotExist: # Captura si el ID es válido pero no existe la terapia
                     return Response(
                         {'error': f'Terapia con ID {terapia_id} no encontrada.'},
                         status=status.HTTP_404_NOT_FOUND
                     )

            serializer = EmotionalPathSerializer(paths, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error al obtener rutas emocionales para {request.user.email}: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Ocurrió un error al obtener las rutas emocionales.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request):
        """
        Activa rutas emocionales (si no existen) basadas en el perfil Y
        asigna un reto diario NO REPETIDO del nivel actual si corresponde.
        """
        try:
            user = request.user
            terapia_id = request.data.get('terapia_id')
            terapia = None
            if terapia_id:
                try:
                    tid = int(terapia_id)
                    terapia = get_object_or_404(Terapia, id=tid)
                    if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                        return Response(
                            {'error': 'No eres miembro de esta terapia.'},
                            status=status.HTTP_403_FORBIDDEN
                        )
                except (ValueError, TypeError):
                    return Response(
                         {'error': 'El ID de la terapia debe ser un número válido.'},
                         status=status.HTTP_400_BAD_REQUEST
                    )
                except Terapia.DoesNotExist:
                     return Response(
                         {'error': f'Terapia con ID {terapia_id} no encontrada.'},
                         status=status.HTTP_404_NOT_FOUND
                     )
            else:
                 return Response(
                    {'error': 'Se requiere el ID de la terapia.'},
                    status=status.HTTP_400_BAD_REQUEST
                 )


            profile = EmotionalProfile.objects.filter(user=user, terapia=terapia).first()
            if not profile:
                return Response(
                    {'error': 'Perfil emocional no encontrado para esta terapia. Por favor, completa la evaluación inicial.'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Obtener o crear el progreso del usuario para esta terapia
            progress, _ = UserPathProgress.objects.get_or_create(
                user=user,
                terapia=terapia,
                defaults={'current_level': 1}
            )
            current_level = progress.current_level

            # Activar rutas basadas en el perfil
            priority_categories = profile.scores.get('high_priority', []) + profile.scores.get('moderate_priority', [])
            active_paths = []
            active_category_ids = []
            for category_name in priority_categories:
                category = Category.objects.filter(name=category_name).first()
                if category:
                    path, created = EmotionalPath.objects.get_or_create(
                        user=user,
                        terapia=terapia,
                        category=category,
                        defaults={'level': current_level, 'is_active': True}
                    )
                    # Si no estaba activa, activarla y asegurar nivel correcto
                    if not path.is_active or path.level != current_level:
                         path.is_active = True
                         path.level = current_level
                         path.save() # Guarda los cambios en la ruta
                    active_paths.append(path)
                    active_category_ids.append(category.id)

            # --- Lógica de Asignación de Reto Diario ---
            today = timezone.localtime(timezone.now()).date()
            challenge_assigned_today = False

            # 1. Verificar si ya hay un reto PENDIENTE para hoy en ESTA terapia
            existing_daily_challenge = UserChallenge.objects.filter(
                user=user,
                terapia=terapia,
                available_date=today,
                is_completed=False
            ).exists()

            if not existing_daily_challenge:
                # 2. Obtener IDs de TODOS los retos YA ASIGNADOS (completados o no) al usuario en ESTA terapia
                assigned_challenge_ids = UserChallenge.objects.filter(
                    user=user,
                    terapia=terapia
                ).values_list('challenge_id', flat=True).distinct()

                # 3. Buscar retos candidatos: Categorías activas, Nivel actual, NO asignados
                assignable_challenges = Challenge.objects.filter(
                    category_id__in=active_category_ids,
                    level=current_level
                ).exclude(
                    id__in=assigned_challenge_ids
                )

                # 4. Seleccionar un reto de los candidatos (aleatorio)
                challenge_to_assign = assignable_challenges.order_by('?').first()

                # 5. Si se encontró un reto asignable, crearlo
                if challenge_to_assign:
                    user_challenge = UserChallenge.objects.create(
                        user=user,
                        terapia=terapia,
                        challenge=challenge_to_assign,
                        available_date=today,
                        assigned_at=timezone.now()
                    )
                    challenge_assigned_today = True
                    logger.info(f"Reto diario '{challenge_to_assign.title}' (ID: {challenge_to_assign.id}, UserChallenge ID: {user_challenge.id}) asignado a {user.email} en terapia {terapia.id}. Nivel: {current_level}. Retos asignables restantes en nivel: {assignable_challenges.count() - 1}")
                else:
                    logger.warning(f"No se encontraron retos nuevos asignables para el usuario {user.email} en terapia {terapia.id} para el nivel {current_level} en las categorías activas ({list(active_category_ids)}).")
            else:
                logger.info(f"El usuario {user.email} ya tiene un reto asignado para hoy ({today}) en la terapia {terapia.id}.")

            # Preparar respuesta
            active_paths_serializer = EmotionalPathSerializer(active_paths, many=True)
            message = "Rutas emocionales verificadas/activadas."
            if challenge_assigned_today:
                message += " Se asignó un nuevo reto diario."
            elif existing_daily_challenge:
                 message += " Ya existe un reto pendiente para hoy."
            else:
                 message += " No se encontraron nuevos retos asignables para el nivel actual."


            return Response(
                {
                    'message': message,
                    'active_paths': active_paths_serializer.data,
                    'current_level': current_level, # Devolver el nivel actual
                    'challenge_assigned_today': challenge_assigned_today # Indicar si se asignó uno hoy
                },
                status=status.HTTP_200_OK # Usar 200 OK porque es una operación idempotente si las rutas ya existen
            )

        except Terapia.DoesNotExist:
             return Response({'error': 'Terapia no encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error al activar rutas/asignar reto para {request.user.email}: {str(e)}", exc_info=True)
            return Response({'error': f'Ocurrió un error interno: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ===========================================================
# --- Clase de Paginación Personalizada (Definir antes de la vista) ---
# ===========================================================
class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10  # Número de resultados por página por defecto
    page_size_query_param = 'page_size' # Permite al frontend cambiar el tamaño con ?page_size=X
    max_page_size = 30 # Límite máximo que el frontend puede solicitar


# ===========================================================
# --- UserChallengeView CON PAGINACIÓN EN GET Y CUIDADO DE PLANTA EN POST ---
# ===========================================================
class UserChallengeView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    pagination_class = StandardResultsSetPagination # Asignar paginador a la vista

    # Propiedad helper para obtener la instancia del paginador
    @property
    def paginator(self):
        if not hasattr(self, '_paginator'):
            self._paginator = self.pagination_class() if self.pagination_class else None
        return self._paginator

    # Método helper para paginar queryset
    def paginate_queryset(self, queryset):
        if self.paginator is None: return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    # Método helper para obtener respuesta paginada
    def get_paginated_response(self, data):
        assert self.paginator is not None
        # Añadimos total_pages aquí directamente para simplificar
        response = self.paginator.get_paginated_response(data)
        try:
            response.data['total_pages'] = self.paginator.page.paginator.num_pages
        except Exception as e:
             logger.warning(f"No se pudo añadir total_pages a la respuesta paginada: {e}")
             response.data['total_pages'] = 1 # O un valor por defecto
        return response

    # --- MÉTODO GET CON PAGINACIÓN ---
    def get(self, request):
        user = request.user
        terapia_id = request.query_params.get('terapia_id')
        status_filter = request.query_params.get('status', 'pending')
        today = timezone.localtime(timezone.now()).date() # Hora local del servidor

        if not terapia_id: return Response({"error": "Se requiere ID terapia."}, status=status.HTTP_400_BAD_REQUEST)

        try:
             tid = int(terapia_id)
             terapia = get_object_or_404(Terapia, id=tid)
             if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                  return Response({"error": "No eres miembro."}, status=status.HTTP_403_FORBIDDEN)
        except (ValueError, TypeError): return Response({'error': 'ID terapia inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        except Terapia.DoesNotExist: return Response({'error': f'Terapia ID {tid} no encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        serializer_context = {'request': request}
        base_queryset = UserChallenge.objects.select_related('challenge__category', 'terapia', 'user', 'collaborative_recipient').filter(user=user, terapia=terapia)

        try:
            if status_filter == 'pending':
                # --- Primero, verifica si YA EXISTE CUALQUIER reto para hoy ---
                challenge_exists_for_today = base_queryset.filter(available_date=today).exists()
                newly_assigned_challenge = None # Para guardar el reto si lo creamos

                # --- Si NO existe NINGUNO para hoy, intenta asignar ---
                if not challenge_exists_for_today:
                    logger.info(f"UCV GET: No existe reto para {user.email} T:{terapia.id} en {today}. Intentando asignar...")
                    try:
                        progress = get_object_or_404(UserPathProgress, user=user, terapia=terapia)
                        current_level = progress.current_level
                        active_category_ids = EmotionalPath.objects.filter(
                            user=user, terapia=terapia, is_active=True, level=current_level
                        ).values_list('category_id', flat=True)

                        if active_category_ids:
                            assigned_challenge_ids = UserChallenge.objects.filter(
                                user=user, terapia=terapia
                            ).values_list('challenge_id', flat=True).distinct()

                            assignable_challenges = Challenge.objects.filter(
                                category_id__in=active_category_ids,
                                level=current_level
                            ).exclude(
                                id__in=assigned_challenge_ids
                            )
                            challenge_to_assign = assignable_challenges.order_by('?').first()

                            if challenge_to_assign:
                                # Crear y guardar en variable temporal
                                newly_assigned_challenge = UserChallenge.objects.create(
                                    user=user,
                                    terapia=terapia,
                                    challenge=challenge_to_assign,
                                    available_date=today,
                                    assigned_at=timezone.now()
                                )
                                logger.info(f"UCV GET: NUEVO Reto '{challenge_to_assign.title}' (UC ID: {newly_assigned_challenge.id}) asignado.")
                            else:
                                logger.warning(f"UCV GET: No se encontraron retos nuevos asignables.")
                        else:
                             logger.warning(f"UCV GET: No hay rutas activas para asignar reto.")

                    except UserPathProgress.DoesNotExist:
                         logger.error(f"UCV GET: Progreso no encontrado al intentar asignar.")
                    except Exception as assign_err:
                         logger.error(f"UCV GET: Error inesperado al asignar reto: {assign_err}", exc_info=True)

                # --- Ahora, SIEMPRE busca el reto PENDIENTE para hoy ---
                # Si se acaba de asignar, será `newly_assigned_challenge`.
                # Si ya existía uno pendiente, lo encontrará aquí.
                # Si ya existía pero estaba completado, no encontrará nada.
                daily = base_queryset.filter(
                    available_date=today,
                    is_completed=False # Solo pendientes
                ).order_by('-assigned_at').first()

                # Busca los retos perdidos (pendientes de días anteriores)
                missed = base_queryset.filter(
                    available_date__lt=today,
                    is_completed=False
                ).order_by('available_date')

                # Construye la respuesta
                response_data = {
                    'daily_challenge': UserChallengeSerializer(daily, context=serializer_context).data if daily else None,
                    'missed_challenges': UserChallengeSerializer(missed, many=True, context=serializer_context).data
                }
                return Response(response_data)

            elif status_filter == 'completed':
                # ... (lógica de completados sin cambios) ...
                completed_qs = base_queryset.filter(is_completed=True).order_by('-completed_at')
                page = self.paginate_queryset(completed_qs)
                if page is not None:
                    serializer = UserChallengeSerializer(page, many=True, context=serializer_context)
                    paginated_response = self.get_paginated_response(serializer.data)
                    paginated_data = paginated_response.data
                    paginated_data['completed_challenges'] = paginated_data.pop('results')
                    return Response(paginated_data)
                else:
                    serializer = UserChallengeSerializer(completed_qs, many=True, context=serializer_context)
                    return Response({'completed_challenges': serializer.data})

            elif status_filter == 'all':
                 # ... (lógica para 'all' sin cambios) ...
                 # NO asigna reto aquí
                pending_qs = base_queryset.filter(is_completed=False, available_date__lte=today)
                daily = pending_qs.filter(available_date=today).order_by('-assigned_at').first()
                missed = pending_qs.filter(available_date__lt=today).order_by('available_date')

                completed_qs = base_queryset.filter(is_completed=True).order_by('-completed_at')
                page = self.paginate_queryset(completed_qs)
                if page is not None:
                    serializer = UserChallengeSerializer(page, many=True, context=serializer_context)
                    paginated_response = self.get_paginated_response(serializer.data)
                    completed_data = paginated_response.data.get('results', [])
                    pagination_metadata = {'count': paginated_response.data.get('count'), 'next': paginated_response.data.get('next'), 'previous': paginated_response.data.get('previous'), 'total_pages': paginated_response.data.get('total_pages')}
                else: serializer = UserChallengeSerializer(completed_qs, many=True, context=serializer_context); completed_data = serializer.data; pagination_metadata = {}
                response_data = { 'daily_challenge': UserChallengeSerializer(daily, context=serializer_context).data if daily else None, 'missed_challenges': UserChallengeSerializer(missed, many=True, context=serializer_context).data, 'completed_challenges': completed_data, **pagination_metadata }
                return Response(response_data)

            else: return Response({'error': 'Filtro status inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error get retos {user.email} T:{tid}: {str(e)}", exc_info=True);
            return Response({'error': f'Error interno get retos: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    # --- MÉTODO POST (sin cambios) ---
# EN therapy/views.py -> dentro de la clase UserChallengeView

    @transaction.atomic
    def post(self, request):
        """
        Marca reto como completado, sube archivo a R2 (si aplica),
        cuida la planta asociada (condicionalmente para grupos) y verifica subida de nivel.
        """
        user = request.user
        user_challenge_id = request.data.get('user_challenge_id')
        terapia_id = request.data.get('terapia_id')
        uploaded_file = request.FILES.get('challenge_file')

        # Validación inicial de IDs
        if not user_challenge_id or not terapia_id:
            return Response({'error': 'Se requieren user_challenge_id y terapia_id.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Conversión y validación de IDs numéricos
            try:
                uc_id = int(user_challenge_id)
                tid = int(terapia_id) # Guardamos tid para logging consistente
            except (ValueError, TypeError):
                return Response({'error': 'ID(s) inválido(s).'}, status=status.HTTP_400_BAD_REQUEST)

            # Obtener el UserChallenge específico, asegurando que pertenece al usuario y terapia, y no está completado
            user_challenge = get_object_or_404(
                UserChallenge.objects.select_related('challenge', 'terapia'), # Optimización con select_related
                id=uc_id,
                user=user,
                terapia_id=tid,
                is_completed=False
            )
            terapia = user_challenge.terapia # Obtenemos el objeto Terapia desde el reto

            # Doble chequeo de membresía (aunque GOSF ya filtra por usuario y terapia_id)
            if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                # Este caso es improbable si GOSF funcionó, pero es una salvaguarda
                logger.warning(f"Usuario {user.email} intentó completar UC {uc_id} de T:{tid} sin ser miembro (¡Inconsistencia!).")
                return Response({'error': 'No eres miembro de esta terapia.'}, status=status.HTTP_403_FORBIDDEN)

            # --- Procesar Contenido y Subir Archivo (si aplica) ---
            content = {}
            challenge_tool = user_challenge.challenge.tools.lower()
            file_required = challenge_tool in ['drawing', 'photo', 'video', 'audio']

            if file_required:
                if uploaded_file:
                    logger.info(f"Archivo '{uploaded_file.name}' recibido para UC:{uc_id}")
                    try:
                        # Generar nombre único y subir a R2
                        object_name = generate_unique_object_name(user.id, user_challenge.challenge.id, uploaded_file.name)
                        file_url = upload_file_to_r2(uploaded_file, settings.AWS_STORAGE_BUCKET_NAME, object_name, uploaded_file.content_type)
                        if not file_url:
                            raise Exception("Fallo la subida del archivo a R2")
                        content.update({
                            'file_url': file_url,
                            'original_filename': uploaded_file.name,
                            'content_type': uploaded_file.content_type,
                            'storage': 'r2'
                        })
                        logger.info(f"Archivo UC:{uc_id} subido a R2: {file_url}")
                    except Exception as e:
                        logger.error(f"Error subiendo archivo a R2 para UC:{uc_id}: {e}", exc_info=True)
                        # Devolver error específico de subida
                        return Response({'error': f'Error al guardar el archivo adjunto: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                else:
                    # Si el reto requiere archivo pero no se envió
                    logger.warning(f"Intento de completar UC:{uc_id} (tool: {challenge_tool}) sin archivo requerido por {user.email}.")
                    return Response({'error': f'Se requiere un archivo para el tipo de reto "{challenge_tool}".'}, status=status.HTTP_400_BAD_REQUEST)

            # Procesar contenido de texto si aplica
            if challenge_tool == 'text':
                content['text'] = request.data.get('text', '')
            elif challenge_tool == 'reflection':
                content['reflection'] = request.data.get('reflection', '')
            elif challenge_tool == 'letter':
                content['letter'] = request.data.get('letter', '')
                content['recipient'] = request.data.get('recipient', 'unknown')

            # Si no hubo contenido específico (ej. solo click en completar), marcarlo
            if not content and not file_required:
                 content['status'] = 'completed_without_specific_content'


            # --- Marcar Reto Como Completado ---
            user_challenge.content = content
            user_challenge.is_completed = True
            user_challenge.completed_at = timezone.now() # Timestamp UTC de completitud

            # Calcular fecha de revelación si aplica (para retos colaborativos usualmente)
            reveal_days = getattr(user_challenge.challenge, 'reveal_after_days', 0)
            if reveal_days and reveal_days > 0:
                 user_challenge.reveal_date = (timezone.now() + timedelta(days=reveal_days)).date()

            user_challenge.save()
            # Loguear ID, fecha y usuario
            logger.info(f"Reto UC:{uc_id} (Fecha: {user_challenge.available_date}) completado por {user.email}.")


            # ===========================================================
            # ▼▼▼▼ LÓGICA MODIFICADA PARA CUIDAR PLANTA ▼▼▼▼
            # ===========================================================
            plant_cared_info = None # Diccionario para la respuesta API
            should_care_plant = False # Flag para decidir si llamar a plant.care()

            # Obtener la fecha del reto que se acaba de completar
            challenge_date = user_challenge.available_date

            try:
                # Obtener la planta asociada a la terapia
                plant = Plant.objects.select_related('terapia').get(terapia=terapia)
                therapy_type = terapia.tipo # 'individual', 'pareja', 'familiar'

                # Decidir si cuidar basado en el tipo de terapia
                if therapy_type == 'individual':
                    should_care_plant = True
                    logger.info(f"[PlantCare] Terapia individual T:{tid}. Se intentará cuidar la planta.")

                elif therapy_type in ['pareja', 'familiar']:
                    logger.info(f"[PlantCare] Terapia grupal ({therapy_type}) T:{tid}. Verificando completitud para fecha {challenge_date}.")
                    members = User.objects.filter(miembroterapia__terapia=terapia)
                    all_members_completed_for_date = True # Asumir verdadero inicialmente

                    if not members.exists():
                         logger.warning(f"[PlantCare] Terapia grupal T:{tid} sin miembros en MiembroTerapia. No se cuidará.")
                         all_members_completed_for_date = False
                    else:
                        logger.debug(f"[PlantCare] Miembros T:{tid}: {[m.email for m in members]}")
                        for member in members:
                            # Verificar si CADA miembro tiene un UserChallenge COMPLETADO para la MISMA fecha
                            member_completed = UserChallenge.objects.filter(
                                user=member,
                                terapia=terapia,
                                available_date=challenge_date, # Crucial: misma fecha del reto actual
                                is_completed=True
                            ).exists()

                            logger.debug(f"[PlantCare] Check Miembro {member.email}, T:{tid}, Fecha: {challenge_date}. Completado: {member_completed}")

                            if not member_completed:
                                all_members_completed_for_date = False
                                logger.info(f"[PlantCare] Miembro {member.email} NO completó reto para {challenge_date} en T:{tid}. Planta NO se cuidará.")
                                break # Optimización: Si uno falta, no seguir verificando

                    if all_members_completed_for_date:
                        should_care_plant = True
                        logger.info(f"[PlantCare] ¡Todos los miembros T:{tid} completaron reto para {challenge_date}! Se intentará cuidar.")

                else:
                     # Caso improbable si los tipos de terapia están bien definidos
                     logger.warning(f"[PlantCare] Tipo de terapia desconocido '{therapy_type}' para T:{tid}. No se cuidará.")

                # --- Llamar a plant.care() SOLO si se determinó que se debe cuidar ---
                if should_care_plant:
                    logger.info(f"***** LLAMANDO A plant.care() para T:{tid}, Usuario que gatilla: {user.email} *****") # LOG DE DEBUG
                    # Llamar al método del modelo Plant, pasando el usuario que completó el reto
                    care_successful, care_message, plant_status_dict = plant.care(caring_user=user) # Llamada al método del modelo
                    plant_cared_info = {"message": care_message, **plant_status_dict} # Construir info para la API

                    # Loguear resultado del cuidado
                    log_msg = f"Planta T:{tid} cuidada exitosamente." if care_successful else f"Planta T:{tid} NO se cuidó hoy (probablemente ya cuidada)."
                    logger.info(f"[PlantCare] Resultado: {log_msg} (Acción por {user.email}). Mensaje: {care_message}")
                elif therapy_type in ['pareja', 'familiar'] and not should_care_plant:
                    # Si es grupal y no todos completaron, añadir mensaje específico
                    plant_cared_info = {
                        "message": "Esperando a que todos los miembros completen el reto de hoy.",
                        "status": "pending_group",
                        "level": plant.level, # Devolver estado actual aunque no se cuide
                        "streak": plant.current_streak,
                        "is_alive": plant.is_alive
                    }
                    logger.info(f"[PlantCare] Terapia grupal T:{tid} incompleta para {challenge_date}. Info devuelta: {plant_cared_info}")


            except Plant.DoesNotExist:
                 logger.warning(f"[PlantCare] Planta no encontrada para T:{tid} al intentar cuidar tras UC:{uc_id}.")
                 plant_cared_info = {"error": "Planta no encontrada."}
            except Exception as plant_error:
                 # Capturar cualquier otro error durante la lógica de cuidado
                 logger.error(f"[PlantCare] Error inesperado procesando cuidado planta T:{tid}: {plant_error}", exc_info=True)
                 plant_cared_info = {"error": f"Error interno procesando cuidado de planta: {str(plant_error)}"}

            # ===========================================================
            # ▲▲▲▲ FIN DE LÓGICA MODIFICADA ▲▲▲▲
            # ===========================================================

            # --- Actualizar Progreso Individual del Usuario ---
            # El progreso individual avanza aunque la planta no se cuide (si es grupal incompleto)
            progress, created = UserPathProgress.objects.get_or_create(
                user=user,
                terapia=terapia,
                defaults={'current_level': 1, 'completed_challenges': 0}
            )
            if created:
                 logger.info(f"Registro de UserPathProgress creado para {user.email} en T:{tid}.")

            # Incrementar contador de retos completados para este usuario
            progress.completed_challenges = F('completed_challenges') + 1
            progress.save(update_fields=['completed_challenges', 'updated_at'])
            logger.debug(f"Progreso individual actualizado para {user.email} en T:{tid}.")


            # --- Lógica de Subida de Nivel (basada en progreso individual) ---
            level_up_occurred = False
            # Recargar el progreso para obtener el valor actualizado de completed_challenges
            progress.refresh_from_db(fields=['completed_challenges', 'current_level'])

            # Verificar si se cumplen condiciones para subir de Nivel 1 a 2
            if progress.current_level == 1:
                 active_paths = EmotionalPath.objects.filter(user=user, terapia=terapia, is_active=True, level=1)
                 if active_paths.exists(): # Solo proceder si hay rutas activas en nivel 1
                     level_one_fully_completed = True # Asumir completado
                     for path in active_paths:
                         # Contar retos totales del nivel 1 para esta categoría
                         total_challenges_level_1 = Challenge.objects.filter(category=path.category, level=1).count()
                         if total_challenges_level_1 == 0: continue # Saltar si la categoría no tiene retos en nivel 1

                         # Contar retos completados por el usuario en nivel 1 para esta categoría
                         completed_in_level_1 = UserChallenge.objects.filter(
                             user=user,
                             terapia=terapia,
                             challenge__category=path.category,
                             challenge__level=1,
                             is_completed=True
                         ).count()

                         # Si los completados son menos que los totales, el nivel no está completo
                         if completed_in_level_1 < total_challenges_level_1:
                             level_one_fully_completed = False
                             logger.debug(f"Nivel 1 T:{tid} para {user.email} NO completo. Cat: {path.category.name} ({completed_in_level_1}/{total_challenges_level_1})")
                             break # Salir del bucle de paths

                     # Si después de verificar todas las rutas activas, el nivel 1 sigue completo...
                     if level_one_fully_completed:
                         logger.info(f"¡Nivel 1 T:{tid} completado por {user.email}!")
                         progress.current_level = 2
                         progress.last_level_up = timezone.now()
                         progress.save(update_fields=['current_level', 'last_level_up', 'updated_at'])

                         # Actualizar el nivel de las rutas activas a 2
                         updated_paths_count = EmotionalPath.objects.filter(
                             user=user, terapia=terapia, is_active=True, level=1
                         ).update(level=2)

                         level_up_occurred = True
                         logger.info(f"{user.email} subió a Nivel 2 en T:{tid}. {updated_paths_count} rutas actualizadas.")

            # --- Preparar Respuesta Final de la API ---
            serializer = UserChallengeSerializer(user_challenge, context={'request': request})
            response_data = {
                'message': 'Reto completado exitosamente.',
                'challenge': serializer.data,
                'level_up': level_up_occurred,
                'plant_care_info': plant_cared_info # Contiene info del cuidado o mensaje de espera
            }
            return Response(response_data, status=status.HTTP_200_OK)

        # --- Manejo de Excepciones Principales ---
        except UserChallenge.DoesNotExist:
             logger.error(f"UC {user_challenge_id} no encontrado o ya completado para {user.email} en T:{tid} durante POST.")
             return Response({'error': 'Reto no encontrado o ya completado.'}, status=status.HTTP_404_NOT_FOUND)
        except Terapia.DoesNotExist: # Captura si la terapia asociada al UC no existe (raro)
            logger.error(f"Terapia {tid} asociada a UC {uc_id} no encontrada.")
            return Response({'error': 'La terapia asociada a este reto no existe.'}, status=status.HTTP_404_NOT_FOUND)
        except Plant.DoesNotExist: # Captura explícita si la planta no existe al intentar cuidarla
            logger.warning(f"Intento de cuidar planta inexistente para T:{tid} tras completar UC:{uc_id}.")
            # Decidir si devolver error 500 o un 200 OK pero con error en plant_care_info
            # Devolver 200 OK es menos disruptivo, la completitud del reto es lo principal.
            serializer = UserChallengeSerializer(user_challenge, context={'request': request}) # Necesitamos user_challenge si llegamos aquí
            response_data = {
                'message': 'Reto completado, pero la planta asociada no fue encontrada.',
                'challenge': serializer.data,
                'level_up': False, # Asumir que no hubo level up si la planta falta
                'plant_care_info': {'error': 'Planta asociada no encontrada.'}
            }
            return Response(response_data, status=status.HTTP_200_OK) # 200 OK con error parcial
        except Exception as e:
             # Captura cualquier otro error inesperado en la transacción
            logger.error(f"Error inesperado en TX de completar UC:{uc_id} para {user.email}: {e}", exc_info=True)
            return Response({'error': 'Ocurrió un error interno al procesar la finalización del reto.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class DailyComponentView(APIView):
    """
    Verifica y registra la finalización de componentes diarios (Diario, Meditación).
    Usa la fecha local del servidor (basada en TIME_ZONE) para determinar 'hoy'.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Verifica si el usuario ha completado los componentes diarios para HOY (fecha local).
        - Diario: Busca una DiaryEntry para el usuario, terapia y fecha local de hoy.
        - Meditación: Busca un DailyComponent tipo 'meditation' para usuario, terapia y fecha local de hoy.
        """
        try:
            user = request.user
            terapia_id_str = request.query_params.get('terapia_id')
            # --- Usa la fecha LOCAL ---
            today = timezone.localtime(timezone.now()).date()
            # ---
            tid = None # Inicializar tid

            completed_status = {
                'diary': False,
                'meditation': False
            }
            # QuerySet vacío para componentes explícitos (meditación)
            explicit_components_qs = DailyComponent.objects.none()

            if not terapia_id_str:
                # Considerar devolver error si siempre se requiere
                 logger.warning(f"GET DailyComponentView sin terapia_id para usuario {user.email}. Devolviendo estado no completado.")
                 # return Response({'error': 'Se requiere el ID de la terapia.'}, status=status.HTTP_400_BAD_REQUEST)
                 # Por ahora, devolvemos False si no hay ID
                 serializer = DailyComponentSerializer(explicit_components_qs, many=True) # Serializador vacío
                 return Response(
                    {'completed': completed_status, 'components': serializer.data},
                    status=status.HTTP_200_OK
                 )

            # Procesar si se proporcionó terapia_id
            try:
                tid = int(terapia_id_str)
                # Verificar que la terapia existe y el usuario es miembro
                terapia = get_object_or_404(Terapia, id=tid)
                if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                     logger.warning(f"Usuario {user.id} intentó acceder a componentes de terapia {tid} sin ser miembro.")
                     return Response({'error': 'No eres miembro de esta terapia.'}, status=status.HTTP_403_FORBIDDEN)

                # --- Comprobar Diario (usando DiaryEntry y fecha local) ---
                completed_status['diary'] = DiaryEntry.objects.filter(
                    user=user,
                    terapia=terapia, # Usar el objeto Terapia directamente es más claro
                    date=today      # Comparar con la fecha LOCAL
                ).exists()
                logger.debug(f"Check diario para {user.id}, Terapia {tid}, Fecha {today}. Existe: {completed_status['diary']}")

                # --- Comprobar Meditación (usando DailyComponent y fecha local) ---
                meditation_component = DailyComponent.objects.filter(
                    user=user,
                    terapia=terapia,
                    date=today,      # Usar fecha LOCAL
                    component_type='meditation'
                ).first()

                if meditation_component:
                    completed_status['meditation'] = True
                    # Añadir el componente de meditación explícito a la query para serializarlo
                    explicit_components_qs = DailyComponent.objects.filter(pk=meditation_component.pk)
                logger.debug(f"Check meditación para {user.id}, Terapia {tid}, Fecha {today}. Existe: {completed_status['meditation']}")


            except (ValueError, TypeError):
                logger.warning(f"ID de terapia inválido recibido: '{terapia_id_str}'")
                return Response({'error': 'ID de terapia inválido.'}, status=status.HTTP_400_BAD_REQUEST)
            # Terapia.DoesNotExist es manejado por get_object_or_404 y devolverá 404

            # Serializar solo los componentes explícitos encontrados (meditación)
            serializer = DailyComponentSerializer(explicit_components_qs, many=True)
            logger.debug(f"Estado componentes final para {user.id}, Terapia {tid}: {completed_status}")

            return Response(
                {'completed': completed_status, 'components': serializer.data},
                status=status.HTTP_200_OK
            )

        # Captura específica por si get_object_or_404 no se maneja como se espera o falla antes
        except Terapia.DoesNotExist:
             logger.warning(f"Intento de acceso a terapia no existente ID: {terapia_id_str} por usuario {request.user.id}")
             return Response({'error': f'Terapia con ID {terapia_id_str} no encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            # Loguear cualquier otro error inesperado
            logger.error(f"Error inesperado al verificar componentes diarios para {request.user.id}: {str(e)}", exc_info=True)
            return Response({'error': 'Error interno al procesar la solicitud.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        """
        Registra la finalización de un componente diario MANUAL (ej. meditación) para HOY (fecha local).
        NO se permite registrar 'diary' por aquí, ya que es automático.
        """
        try:
            user = request.user
            component_type = request.data.get('component_type')
            terapia_id_str = request.data.get('terapia_id')
            # --- Usa la fecha LOCAL ---
            today = timezone.localtime(timezone.now()).date()
            # ---
            tid = None # Para logging
            terapia = None

            if not terapia_id_str:
                 return Response(
                    {'error': 'Se requiere el ID de la terapia.'},
                    status=status.HTTP_400_BAD_REQUEST
                 )

            # --- VALIDACIÓN DE TERAPIA ---
            try:
                tid = int(terapia_id_str)
                terapia = get_object_or_404(Terapia, id=tid)
                if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                    logger.warning(f"Usuario {user.id} intentó registrar componente en terapia {tid} sin ser miembro.")
                    return Response(
                        {'error': 'No eres miembro de esta terapia.'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            except (ValueError, TypeError):
                 logger.warning(f"POST DailyComponent: ID de terapia inválido recibido: '{terapia_id_str}'")
                 return Response({'error': 'ID de terapia inválido.'}, status=status.HTTP_400_BAD_REQUEST)
            # Terapia.DoesNotExist manejado por get_object_or_404

            # --- VALIDACIÓN DEL TIPO DE COMPONENTE ---
            allowed_manual_components = ['meditation'] # Solo meditación se registra manualmente
            if component_type not in allowed_manual_components:
                 if component_type == 'diary':
                      logger.warning(f"Usuario {user.id} intentó registrar 'diary' manualmente para terapia {tid}.")
                      return Response(
                          {'error': 'La finalización del diario se registra automáticamente al crear una entrada.'},
                          status=status.HTTP_400_BAD_REQUEST
                      )
                 logger.warning(f"Usuario {user.id} intentó registrar tipo inválido '{component_type}' para terapia {tid}.")
                 return Response(
                     {'error': f"Tipo de componente '{component_type}' inválido o no registrable manualmente."},
                     status=status.HTTP_400_BAD_REQUEST
                 )

            # --- LÓGICA PARA COMPONENTES MANUALES (Meditación) ---
            # Verificar si ya existe para HOY (fecha local)
            existing_component = DailyComponent.objects.filter(
                user=user,
                terapia=terapia,
                component_type=component_type, # Será 'meditation'
                date=today                      # Usar fecha LOCAL
            ).first()

            if existing_component:
                 serializer = DailyComponentSerializer(existing_component)
                 logger.info(f"Componente '{component_type}' ya registrado hoy ({today}) para {user.email} en terapia {tid}.")
                 return Response(
                     {'message': f'Componente diario ({component_type}) ya registrado para hoy.', 'component': serializer.data},
                     status=status.HTTP_200_OK # OK porque ya está hecho
                 )

            # Si no existe, crear uno nuevo usando la fecha local
            component = DailyComponent.objects.create(
                user=user,
                terapia=terapia,
                component_type=component_type, # Será 'meditation'
                date=today,                      # Usar fecha LOCAL
                completed_at=timezone.now()      # Usar el timestamp actual UTC para completed_at
            )
            serializer = DailyComponentSerializer(component)
            logger.info(f"Componente diario '{component_type}' registrado para {user.email} en terapia {tid} en fecha {today}.")
            return Response(
                {'message': f'Componente diario ({component_type}) registrado exitosamente.', 'component': serializer.data},
                status=status.HTTP_201_CREATED
            )

        # Captura específica por si get_object_or_404 no se maneja como se espera o falla antes
        except Terapia.DoesNotExist:
             logger.warning(f"POST DailyComponent: Intento de acceso a terapia no existente ID: {terapia_id_str} por usuario {request.user.id}")
             return Response({'error': f'Terapia con ID {terapia_id_str} no encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error inesperado al registrar componente diario manual para {request.user.id}: {str(e)}", exc_info=True)
            return Response({'error': 'Error interno al procesar la solicitud.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class CollaborativeChallengeView(APIView):
    permission_classes = [IsAuthenticated]

    # Este endpoint podría necesitar parser_classes = [JSONParser, FormParser, MultiPartParser]
    # si los retos colaborativos también pueden incluir archivos.
    # Por ahora, asumimos que solo son datos JSON (IDs y email).

    def post(self, request):
        """
        Asigna un reto colaborativo y lo envía por chat.
        """
        try:
            user = request.user
            terapia_id = request.data.get('terapia_id')
            challenge_id = request.data.get('challenge_id')
            recipient_email = request.data.get('recipient_email')

            if not terapia_id or not challenge_id or not recipient_email:
                 return Response(
                    {'error': 'Se requieren terapia_id, challenge_id y recipient_email.'},
                    status=status.HTTP_400_BAD_REQUEST
                 )

            try:
                 tid = int(terapia_id)
                 cid = int(challenge_id)
            except (ValueError, TypeError):
                 return Response({'error': 'ID(s) de terapia/reto inválido(s).'}, status=status.HTTP_400_BAD_REQUEST)


            terapia = get_object_or_404(Terapia, id=tid)
            if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                return Response(
                    {'error': 'No eres miembro de esta terapia.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Asegurarse de que el reto exista y sea colaborativo
            challenge = get_object_or_404(Challenge, id=cid, mode_collaborative=True)

            # Encontrar al destinatario y verificar que sea miembro de la misma terapia
            try:
                 recipient = User.objects.get(email__iexact=recipient_email.lower()) # Búsqueda insensible a mayúsculas
            except User.DoesNotExist:
                 return Response(
                    {'error': 'El usuario destinatario no existe.'},
                    status=status.HTTP_400_BAD_REQUEST
                 )

            if not MiembroTerapia.objects.filter(terapia=terapia, usuario=recipient).exists():
                return Response(
                    {'error': 'El destinatario no es miembro de esta terapia.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Verificar si el reto colaborativo ya fue asignado A ESTE RECIPIENTE por ESTE USUARIO en ESTA TERAPIA
            # La unicidad podría ser compleja aquí. Una opción simple es verificar si ya existe
            # un UserChallenge *pendiente* para este usuario, esta terapia, este reto Y este recipiente.
            # O si tu lógica permite múltiples asignaciones, podrías quitar esta verificación.
            existing_collaborative_challenge = UserChallenge.objects.filter(
                user=user,
                terapia=terapia,
                challenge=challenge,
                collaborative_recipient=recipient,
                is_completed=False # Solo si está pendiente
            ).first()

            if existing_collaborative_challenge:
                 # Ya existe un reto colaborativo pendiente con este usuario
                 serializer = UserChallengeSerializer(existing_collaborative_challenge)
                 return Response(
                    {'message': 'Este reto colaborativo ya fue asignado a este usuario.', 'challenge': serializer.data},
                    status=status.HTTP_200_OK # Usar 200 OK ya que no se creó uno nuevo
                 )


            # Si no existe pendiente, crear uno nuevo
            user_challenge = UserChallenge.objects.create(
                user=user,
                terapia=terapia,
                challenge=challenge,
                collaborative_recipient=recipient,
                # Los retos colaborativos no tienen available_date diaria por defecto,
                # pero podrías añadirlo si tu lógica lo requiere.
            )
            logger.info(f"Reto colaborativo '{challenge.title}' (ID: {challenge.id}, UserChallenge ID: {user_challenge.id}) asignado por {user.email} a {recipient.email} en terapia {terapia.id}.")


            # Enviar mensaje por chat
            try:
                message_content = (
                    f"¡Hola {recipient.first_name or recipient.email}! "
                    f"@{user.first_name or user.email} te ha invitado a realizar un reto colaborativo: "
                    f"'{challenge.title}'.\n\nDescripción: {challenge.description}\n\n"
                    f"¡Hablen sobre cómo les gustaría abordarlo juntos!"
                    # Podrías añadir un enlace profundo a la app/reto aquí si lo tienes
                )
                # Asumiendo que Mensaje model tiene usuario (remitente) y terapia
                Mensaje.objects.create(
                    terapia=terapia,
                    usuario=user, # El que inicia la invitación
                    contenido=message_content
                    # Considera si necesitas un campo para el destinatario específico en Mensaje
                )
                logger.info(f"Mensaje de reto colaborativo enviado en chat de terapia {terapia.id}.")
            except Exception as chat_error:
                 logger.error(f"Error al enviar mensaje de chat para reto colaborativo {user_challenge.id}: {chat_error}", exc_info=True)
                 # Decide si esto debe ser un error fatal o solo un warning


            serializer = UserChallengeSerializer(user_challenge)
            # Nota: level_up no aplica a la asignación inicial de retos colaborativos.
            # La variable level_completed en tu código original estaba sin definir aquí.
            # La respuesta para la asignación es diferente a la de completar un reto diario/individual.
            return Response(
                {
                    'message': 'Reto colaborativo asignado exitosamente y notificado por chat.',
                    'challenge': serializer.data,
                },
                status=status.HTTP_201_CREATED # 201 porque creamos un nuevo UserChallenge
            )

        except Terapia.DoesNotExist:
             return Response({'error': 'Terapia no encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        except Challenge.DoesNotExist:
             return Response({'error': 'Reto no encontrado o no es colaborativo.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error al asignar reto colaborativo: {str(e)}", exc_info=True)
            return Response({'error': f'Error interno al asignar reto colaborativo: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UserPathProgressView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Obtiene el progreso actual (nivel) del usuario para una terapia específica.
        Lo crea con nivel 1 si no existe.
        """
        terapia_id = request.query_params.get('terapia_id')
        user = request.user

        if not terapia_id:
            return Response(
                {"error": "Se requiere el ID de la terapia."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Validar que terapia_id sea un entero y que la terapia exista y el usuario sea miembro
            tid = int(terapia_id)
            terapia = get_object_or_404(Terapia, id=tid)
            if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                 return Response(
                    {"error": "No eres miembro de esta terapia."},
                    status=status.HTTP_403_FORBIDDEN
                )

            # INTENTA OBTENER O CREAR EL PROGRESO
            progress, created = UserPathProgress.objects.get_or_create(
                user=user,
                terapia=terapia, # Usa el objeto Terapia obtenido
                defaults={'current_level': 1, 'completed_challenges': 0} # Valores por defecto si se crea
            )

            if created:
                logger.info(f"Registro de progreso creado para usuario {user.email} en terapia {tid}.")

            serializer = UserPathProgressSerializer(progress)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Terapia.DoesNotExist:
             return Response({'error': f'Terapia con ID {terapia_id} no encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        except (ValueError, TypeError):
             return Response({'error': 'ID de terapia inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error al obtener/crear progreso para {user.email} en terapia {terapia_id}: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Error interno al obtener el progreso.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# --- Vista para Reemplazar el Reto Diario (Sin cambios) ---
class ReplaceDailyChallengeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Reemplaza el reto diario PENDIENTE actual por uno nuevo disponible.
        """
        user = request.user
        terapia_id = request.data.get('terapia_id')
        today = timezone.localtime(timezone.now()).date()

        if not terapia_id:
            return Response(
                {'error': 'Se requiere el ID de la terapia.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Validar terapia y membresía
            try:
                 tid = int(terapia_id)
                 terapia = get_object_or_404(Terapia, id=tid)
                 if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                      return Response({"error": "No eres miembro de esta terapia."}, status=status.HTTP_403_FORBIDDEN)
            except (ValueError, TypeError):
                 return Response({'error': 'ID de terapia inválido.'}, status=status.HTTP_400_BAD_REQUEST)
            except Terapia.DoesNotExist:
                 return Response({'error': f'Terapia con ID {terapia_id} no encontrada.'}, status=status.HTTP_404_NOT_FOUND)


            # 1. Encontrar el reto diario PENDIENTE actual
            try:
                current_daily_challenge = UserChallenge.objects.select_related('challenge').get(
                    user=user,
                    terapia=terapia,
                    available_date=today,
                    is_completed=False
                )
            except UserChallenge.DoesNotExist:
                return Response(
                    {'error': 'No hay un reto diario pendiente para reemplazar hoy.'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except UserChallenge.MultipleObjectsReturned:
                logger.error(f"Múltiples retos diarios pendientes encontrados para {user.email} hoy en terapia {terapia_id}.")
                return Response({'error': 'Error de consistencia de datos (múltiples retos diarios).'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            original_challenge_id = current_daily_challenge.challenge.id
            user_challenge_id_to_delete = current_daily_challenge.id

            # 2. Eliminar el UserChallenge actual
            current_daily_challenge.delete(); # Borra el objeto UserChallenge
            logger.info(f"Reto diario original (UserChallenge ID: {user_challenge_id_to_delete}, Challenge ID: {original_challenge_id}) eliminado para {user.email} en terapia {terapia_id}.")

            # Nota: La eliminación del archivo en R2 asociado al UserChallenge ELIMINADO
            # NO sucede automáticamente. Si quieres borrar el archivo cuando el UserChallenge
            # se elimina, necesitarías implementar un signal (post_delete) en Django.

            # 3. Encontrar un NUEVO reto asignable
            progress = get_object_or_404(UserPathProgress, user=user, terapia=terapia)
            current_level = progress.current_level

            active_category_ids = EmotionalPath.objects.filter(
                user=user, terapia=terapia, is_active=True
            ).values_list('category_id', flat=True)
            if not active_category_ids:
                 logger.warning(f"Intento de reemplazar reto para {user.email} sin rutas activas en terapia {terapia_id}.")
                 return Response({'error': 'No tienes rutas emocionales activas para asignar un nuevo reto.'}, status=status.HTTP_400_BAD_REQUEST)


            # Obtener IDs de TODOS los retos YA ASIGNADOS alguna vez, incluyendo el que acabamos de borrar
            # Esto es clave para no asignar el mismo reto que se acaba de saltar
            assigned_challenge_ids = UserChallenge.objects.filter(
                user=user,
                terapia=terapia
            ).values_list('challenge_id', flat=True).distinct()

             # También debemos considerar el ID del reto base del UserChallenge que acabamos de eliminar,
             # ya que no queremos asignarlo de nuevo hoy.
            ids_to_exclude = list(assigned_challenge_ids) + [original_challenge_id]


            # Buscar retos candidatos: Categorías activas, Nivel actual, NO asignados alguna vez, EXCLUYENDO el original
            assignable_challenges = Challenge.objects.filter(
                category_id__in=active_category_ids,
                level=current_level
            ).exclude(
                id__in=ids_to_exclude # ¡La clave para no repetir el saltado!
            )


            # Seleccionar uno aleatorio
            new_challenge_to_assign = assignable_challenges.order_by('?').first()

            # 4. Si se encontró uno nuevo, crearlo
            if new_challenge_to_assign:
                new_user_challenge = UserChallenge.objects.create(
                    user=user,
                    terapia=terapia,
                    challenge=new_challenge_to_assign,
                    available_date=today, # Asignar para hoy
                    assigned_at=timezone.now()
                )
                logger.info(f"Nuevo reto diario '{new_challenge_to_assign.title}' (ID: {new_challenge_to_assign.id}, UserChallenge ID: {new_user_challenge.id}) asignado a {user.email} en terapia {terapia.id} tras reemplazo.")

                # Serializar y devolver el NUEVO reto
                serializer = UserChallengeSerializer(new_user_challenge)
                return Response(serializer.data, status=status.HTTP_201_CREATED) # 201 porque creamos un nuevo recurso
            else:
                # No se encontraron alternativas
                logger.warning(f"No se encontraron retos alternativos para {user.email} en terapia {terapia.id} (Nivel {current_level}, Categorías {list(active_category_ids)}) excluyendo IDs: {ids_to_exclude}.")
                # Devolvemos un error indicando que no hay más opciones hoy.
                # El reto original ya fue eliminado. El usuario no tendrá reto diario hoy.
                return Response(
                    {'error': 'No se encontraron más retos alternativos disponibles para hoy.'},
                    status=status.HTTP_404_NOT_FOUND # 404 porque no se encontró un nuevo recurso asignable
                )

        except Terapia.DoesNotExist:
             return Response({'error': 'Terapia no encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        except UserPathProgress.DoesNotExist:
             logger.error(f"Progreso no encontrado para {user.email} en terapia {terapia_id} durante reemplazo.")
             return Response({'error': 'No se encontró tu registro de progreso.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error al reemplazar reto diario para {user.email} en terapia {terapia_id}: {str(e)}", exc_info=True)
            return Response({'error': 'Error interno al intentar reemplazar el reto.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- FIN DE ReplaceDailyChallengeView ---
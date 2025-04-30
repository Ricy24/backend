# psychologist/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from django.utils import timezone
from django.db.models import Prefetch, Q
from django.core.paginator import Paginator
from datetime import datetime, timedelta
from .models import PsychologistProfile, Availability, Specialty, Certification
from .serializers import PsychologistSerializer, AvailabilitySerializer, PsychologistProfileSerializer, LanguageSerializer, SpecialtySerializer
from api.serializers import  UserSerializer 
from api.models import MiembroTerapia, Usuario
from psychologist.models import Language
from api.models import Usuario
from google_calendar.models import CalendarEvent
import logging
from therapy.models import UserChallenge # Importar UserChallenge
from therapy.serializers import UserChallengeSerializer # Importar el
from django.conf import settings
from django.core.cache import cache
from django.utils.dateparse import parse_datetime
from django.db import transaction
from rest_framework.generics import ListAPIView
from django.core.exceptions import ValidationError
from rest_framework.generics import RetrieveAPIView 
from django.db import models
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404

from rest_framework.parsers import MultiPartParser, FormParser

logger = logging.getLogger(__name__)

class PsychologistRateThrottle(UserRateThrottle):
    rate = '100/hour'

class GetPsychologistAvailabilityView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PsychologistRateThrottle]

    def validate_date_params(self, date_str, duration):
        """Validar parámetros de fecha y duración"""
        if not date_str:
            raise ValueError('Se requiere la fecha (YYYY-MM-DD)')
        
        try:
            requested_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError('Formato de fecha inválido (use YYYY-MM-DD)')

        if duration not in [30, 45, 60]:
            raise ValueError('Duración debe ser 30, 45 o 60 minutos')

        requested_datetime = timezone.make_aware(datetime.combine(requested_date, datetime.min.time()))
        if requested_datetime < timezone.now():
            raise ValueError('No se puede consultar disponibilidad para fechas pasadas')

        return requested_date, requested_datetime

    def get_available_slots(self, psychologist, requested_date, duration, start_time, end_time):
        """Calcular slots disponibles para un psicólogo"""
        available_slots = []
        current_slot = start_time
        session_duration = timedelta(minutes=duration)

        while current_slot + session_duration <= end_time:
            current_slot = current_slot.replace(second=0, microsecond=0)
            if current_slot.minute % duration != 0:
                current_slot += timedelta(minutes=(duration - current_slot.minute % duration))

            cache_key = f'conflicts_{psychologist.id}_{current_slot.isoformat()}'
            conflicts = cache.get(cache_key)
            
            if conflicts is None:
                conflicts = CalendarEvent.objects.filter(
                    psychologist=psychologist,
                    type__in=['therapy', 'group'],
                    start_time__lt=current_slot + session_duration,
                    end_time__gt=current_slot
                ).exists()
                cache.set(cache_key, conflicts, timeout=300)

            if not conflicts:
                available_slots.append(current_slot.strftime('%H:%M'))

            current_slot += timedelta(minutes=duration)

        return available_slots

    def get(self, request):
        try:
            date_str = request.query_params.get('date')
            detailed = request.query_params.get('detailed', 'false').lower() == 'true'
            free_session_only = request.query_params.get('free_session_only', 'false').lower() == 'true'
            duration = int(request.query_params.get('duration', 30))

            requested_date, requested_datetime = self.validate_date_params(date_str, duration)

            psychologists = Usuario.objects.filter(
                is_psychologist=True
            ).select_related(
                'psychologist_profile'
            ).prefetch_related(
                'availability'
            )

            if free_session_only:
                psychologists = psychologists.filter(
                    psychologist_profile__offers_free_30min_session=True
                )

            if not psychologists.exists():
                error_msg = 'No hay psicólogos disponibles'
                if free_session_only:
                    error_msg += ' que ofrezcan sesiones gratuitas'
                return Response(
                    {'error': error_msg},
                    status=status.HTTP_404_NOT_FOUND
                )

            day_of_week = requested_date.strftime('%A')
            available_slots_by_psychologist = {}

            for psychologist in psychologists:
                availability = psychologist.availability.filter(
                    day_of_week=day_of_week
                ).first()

                if not availability:
                    continue

                start_time = timezone.make_aware(
                    datetime.combine(requested_date, availability.start_time)
                )
                end_time = timezone.make_aware(
                    datetime.combine(requested_date, availability.end_time)
                )

                if start_time < timezone.now():
                    start_time = timezone.now().replace(second=0, microsecond=0)
                    start_time += timedelta(minutes=(duration - start_time.minute % duration))

                available_slots = self.get_available_slots(
                    psychologist, requested_date, duration, start_time, end_time
                )

                if available_slots:
                    available_slots_by_psychologist[psychologist.id] = {
                        'psychologist': {
                            'id': psychologist.id,
                            'nombre': psychologist.nombre or psychologist.email,
                            'email': psychologist.email,
                            'profile_pic': psychologist.profile_pic.url if psychologist.profile_pic else None,
                            'offers_free_30min_session': (
                                hasattr(psychologist, 'psychologist_profile') and 
                                psychologist.psychologist_profile.offers_free_30min_session
                            )
                        },
                        'slots': available_slots,
                        'duration': duration
                    }

            if not available_slots_by_psychologist:
                return Response(
                    {'available_slots': []} if detailed else {'start': '', 'end': ''},
                    status=status.HTTP_200_OK
                )

            if detailed:
                return Response(
                    {'available_slots': list(available_slots_by_psychologist.values())},
                    status=status.HTTP_200_OK
                )
            
            first_psychologist_slots = next(iter(available_slots_by_psychologist.values()))
            return Response({
                'start': first_psychologist_slots['slots'][0],
                'end': first_psychologist_slots['slots'][-1],
                'psychologist_id': first_psychologist_slots['psychologist']['id'],
                'duration': first_psychologist_slots['duration']
            }, status=status.HTTP_200_OK)

        except ValueError as ve:
            logger.warning(f"Error de validación: {str(ve)}")
            return Response(
                {'error': str(ve)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error en GetPsychologistAvailabilityView: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Error interno del servidor'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([PsychologistRateThrottle])
def get_psychologists(request):
    try:
        specialty = request.query_params.get('specialty')
        page_number = request.query_params.get('page', 1)
        page_size = request.query_params.get('size', 10)

        psychologists = Usuario.objects.filter(
            is_psychologist=True
        ).prefetch_related(
            Prefetch('availability', queryset=Availability.objects.all()),
            Prefetch('psychologist_profile', queryset=PsychologistProfile.objects.all()),
            Prefetch('psychologist_profile__specialties', queryset=Specialty.objects.all()),
            Prefetch('psychologist_profile__languages', queryset=Language.objects.all()),
            Prefetch('psychologist_profile__certifications', queryset=Certification.objects.all())
        )

        if specialty:
            psychologists = psychologists.filter(
                psychologist_profile__specialties__name=specialty
            ).distinct()

        paginator = Paginator(psychologists, page_size)
        current_page = paginator.get_page(page_number)

        if paginator.count == 0:
            logger.warning("No hay psicólogas registradas")
            return Response(
                {
                    'error': 'No hay psicólogas disponibles',
                    'total': 0,
                    'psychologists': []
                },
                status=status.HTTP_404_NOT_FOUND
            )

        if paginator.count == 1:
            psychologist = current_page[0]
            serializer = PsychologistSerializer(psychologist, context={'request': request})
            response_data = {
                'single_psychologist': True,
                'psychologist': serializer.data,
                'total': 1,
                'page': 1,
                'total_pages': 1
            }
        else:
            serializer = PsychologistSerializer(current_page, many=True, context={'request': request})
            response_data = {
                'single_psychologist': False,
                'psychologists': serializer.data,
                'total': paginator.count,
                'page': current_page.number,
                'total_pages': paginator.num_pages
            }

        logger.debug(f"Retornando {len(current_page)} psicólogas de un total de {paginator.count}")
        return Response(response_data, status=status.HTTP_200_OK)

    except ValueError as ve:
        logger.warning(f"Error de validación: {str(ve)}")
        return Response(
            {'error': 'Parámetros inválidos'},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Error interno del servidor'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
def get_psychologist_availability(request, psychologist_id):
    try:
        psychologist = Usuario.objects.get(id=psychologist_id, is_psychologist=True)
        availability = Availability.objects.filter(psychologist=psychologist)
        serializer = AvailabilitySerializer(availability, many=True)
        logger.debug(f"Disponibilidad devuelta para psicólogo ID {psychologist_id}")
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Usuario.DoesNotExist:
        logger.warning(f"Psicólogo con ID {psychologist_id} no encontrado")
        return Response(
            {'error': 'Psicólogo no encontrado'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error en get_psychologist_availability: {str(e)}")
        return Response(
            {'error': 'Error interno del servidor'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated]) # <-- Añadido: Asegura que el usuario esté autenticado
def create_psychologist_availability(request):
    # Verifica explícitamente si es psicólogo DESPUÉS de la autenticación
    if not hasattr(request.user, 'is_psychologist') or not request.user.is_psychologist:
        return Response(
            {'error': 'No autorizado. Debes ser un psicólogo registrado.'},
            status=status.HTTP_403_FORBIDDEN
        )

    # Usa request.data directamente, no necesitas copiar ni modificarlo aquí
    serializer = AvailabilitySerializer(data=request.data)

    if serializer.is_valid():
        try:
            # --- ¡CAMBIO PRINCIPAL AQUÍ! ---
            # Pasa el psicólogo autenticado directamente al método save()
            # DRF lo asociará correctamente al crear la instancia del modelo.
            serializer.save(psychologist=request.user)

            # Cambiado a logger.info para eventos exitosos
            logger.info(f"Disponibilidad creada para psicólogo {request.user.email}") # Usa email que es único
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except ValidationError as ve:
            # Captura errores de validación del modelo (ej: model.clean() por solapamiento)
            # Los errores del serializer.is_valid() ya se manejan en el 'else'
            logger.warning(f"Error de validación del modelo al guardar disponibilidad para {request.user.email}: {ve}")
            # Devuelve los errores de validación específicos si es posible
            error_detail = ve.message_dict if hasattr(ve, 'message_dict') else {'non_field_errors': ve.messages}
            return Response(error_detail, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e_save:
            # Captura cualquier otro error inesperado durante el guardado
            logger.error(f"Error inesperado al guardar disponibilidad para {request.user.email}: {e_save}", exc_info=True)
            return Response(
                {'error': 'Ocurrió un error interno al intentar guardar la disponibilidad.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        # Los errores de validación del propio serializer (campos faltantes, formato incorrecto)
        logger.warning(f"Error de validación del serializer en create_psychologist_availability para {request.user.email}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['PUT'])
def update_psychologist_availability(request, availability_id):
    try:
        if not request.user.is_authenticated or not request.user.is_psychologist:
            return Response(
                {'error': 'No autorizado. Debes ser un psicólogo registrado.'},
                status=status.HTTP_403_FORBIDDEN
            )

        availability = Availability.objects.get(id=availability_id, psychologist=request.user)
        serializer = AvailabilitySerializer(availability, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.debug(f"Disponibilidad ID {availability_id} actualizada para psicólogo {request.user.nombre or request.user.email}")
            return Response(serializer.data, status=status.HTTP_200_OK)
        logger.warning(f"Error de validación en update_psychologist_availability: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Availability.DoesNotExist:
        logger.warning(f"Disponibilidad ID {availability_id} no encontrada")
        return Response(
            {'error': 'Disponibilidad no encontrada'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error en update_psychologist_availability: {str(e)}")
        return Response(
            {'error': 'Error interno del servidor'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['DELETE'])
def delete_psychologist_availability(request, availability_id):
    try:
        if not request.user.is_authenticated or not request.user.is_psychologist:
            return Response(
                {'error': 'No autorizado. Debes ser un psicólogo registrado.'},
                status=status.HTTP_403_FORBIDDEN
            )

        availability = Availability.objects.get(id=availability_id, psychologist=request.user)
        availability.delete()
        logger.debug(f"Disponibilidad ID {availability_id} eliminada para psicólogo {request.user.nombre or request.user.email}")
        return Response(status=status.HTTP_204_NO_CONTENT)

    except Availability.DoesNotExist:
        logger.warning(f"Disponibilidad ID {availability_id} no encontrada")
        return Response(
            {'error': 'Disponibilidad no encontrada'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error en delete_psychologist_availability: {str(e)}")
        return Response(
            {'error': 'Error interno del servidor'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def create_psychologist_profile(request):
    """
    Crea o actualiza el perfil de un psicólogo autenticado con validaciones mejoradas.
    """
    try:
        if not request.user.is_authenticated or not request.user.is_psychologist:
            return Response(
                {'error': 'No autorizado. Debes ser un psicólogo registrado.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Validar y sanitizar datos
        data = request.data.copy()
        specialties = data.get('specialties', [])
        if not isinstance(specialties, list):
            return Response(
                {'error': 'Las especialidades deben ser una lista'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Limitar número de especialidades
        if len(specialties) > 10:
            return Response(
                {'error': 'Máximo 10 especialidades permitidas'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Sanitizar especialidades
        valid_specialties = [
            s.strip()[:50] for s in specialties
            if isinstance(s, str) and s.strip()
        ]

        # Validar años de experiencia
        years_experience = data.get('years_experience', 0)
        try:
            years_experience = int(years_experience)
            if years_experience < 0 or years_experience > 70:
                raise ValueError('Años de experiencia inválidos')
        except (ValueError, TypeError):
            return Response(
                {'error': 'Años de experiencia inválidos'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validar duración de sesiones
        session_duration = data.get('session_duration', 60)
        if session_duration not in [30, 45, 60, 90]:
            return Response(
                {'error': 'Duración de sesión inválida'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Sanitizar descripción
        description = data.get('description', '').strip()[:1000]

        with transaction.atomic():
            profile, created = PsychologistProfile.objects.get_or_create(
                user=request.user,
                defaults={
                    'specialties': valid_specialties,
                    'years_experience': years_experience,
                    'session_duration': session_duration,
                    'description': description,
                    'offers_free_30min_session': data.get('offers_free_30min_session', False),
                    'is_accepting_patients': data.get('is_accepting_patients', True)
                }
            )

            if not created:
                # Actualizar campos existentes
                profile.specialties = valid_specialties
                profile.years_experience = years_experience
                profile.session_duration = session_duration
                profile.description = description
                profile.offers_free_30min_session = data.get('offers_free_30min_session', profile.offers_free_30min_session)
                profile.is_accepting_patients = data.get('is_accepting_patients', profile.is_accepting_patients)
                profile.save()

            # Invalidar cache relacionado
            cache_keys = [
                f'psychologist_profile_{request.user.id}',
                'psychologist_list',
                f'psychologist_availability_{request.user.id}'
            ]
            cache.delete_many(cache_keys)

            # Preparar respuesta
            response_data = {
                'id': profile.id,
                'specialties': profile.specialties,
                'years_experience': profile.years_experience,
                'session_duration': profile.session_duration,
                'description': profile.description,
                'offers_free_30min_session': profile.offers_free_30min_session,
                'is_accepting_patients': profile.is_accepting_patients,
                'created_at': profile.created_at.isoformat() if profile.created_at else None,
                'updated_at': profile.updated_at.isoformat() if profile.updated_at else None
            }

            logger.info(
                f"Perfil de psicólogo {'creado' if created else 'actualizado'}: {request.user.email}",
                extra={
                    'user_id': request.user.id,
                    'profile_id': profile.id,
                    'specialties_count': len(valid_specialties)
                }
            )

            return Response(
                response_data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
            )

    except ValidationError as ve:
        logger.warning(f"Error de validación: {str(ve)}")
        return Response(
            {'error': str(ve)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(
            f"Error en create_psychologist_profile: {str(e)}",
            exc_info=True,
            extra={'user_id': request.user.id if request.user else None}
        )
        return Response(
            {'error': 'Error interno del servidor'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class GetMyPsychologistProfileView(APIView):
    """
    Obtiene el perfil combinado (Usuario + PsychologistProfile)
    del psicólogo autenticado.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.is_psychologist:
            return Response({'error': 'Acceso denegado. Se requiere cuenta de psicólogo.'}, status=status.HTTP_403_FORBIDDEN)

        # Intenta obtener el perfil profesional
        profile = getattr(user, 'psychologist_profile', None)

        # Serializar datos (idealmente con un serializer combinado)
        # Ejemplo usando serializers separados:
        user_data = UserSerializer(user).data # Asegúrate que UserSerializer incluya profile_pic
        profile_data = PsychologistProfileSerializer(profile).data if profile else None

        # Combina los datos como espera el frontend
        response_data = {
            **user_data, # Datos del Usuario
            # Anidar datos del perfil si PsychologistProfileSerializer los devuelve estructurados
            # O desestructurar aquí si es necesario:
            'bio': profile_data.get('bio') if profile_data else None,
            'years_experience': profile_data.get('years_experience') if profile_data else None,
            'therapeutic_approach': profile_data.get('therapeutic_approach') if profile_data else None,
            'offers_free_30min_session': profile_data.get('offers_free_30min_session') if profile_data else False,
            'specialties': profile_data.get('specialties') if profile_data else [],
            'languages': profile_data.get('languages') if profile_data else [],
            # Asegúrate que 'profile_pic' venga de user_data
        }

        return Response(response_data, status=status.HTTP_200_OK)


class UpdateMyPsychologistProfileView(APIView):
    """
    Actualiza el perfil (Usuario + PsychologistProfile) del psicólogo autenticado.
    Acepta PATCH para actualizaciones parciales y maneja FormData para la foto.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def patch(self, request):
        user = request.user
        if not user.is_psychologist:
            return Response({'error': 'Acceso denegado.'}, status=status.HTTP_403_FORBIDDEN)

        profile, created = PsychologistProfile.objects.get_or_create(user=user) # Obtiene o crea el perfil

        # --- Es MUY RECOMENDABLE crear un serializer específico para esta actualización ---
        # serializer = UpdateMyPsychologistProfileSerializer(user, data=request.data, partial=True, context={'request': request})
        # if serializer.is_valid():
        #     updated_user, updated_profile = serializer.save()
        #     # Re-serializar la respuesta completa
        #     response_serializer = GetMyPsychologistProfileCombinedSerializer(updated_user) # Un serializer para la respuesta
        #     return Response({
        #          'message': 'Perfil actualizado exitosamente.',
        #          **response_serializer.data # Devolver el perfil completo actualizado
        #      }, status=status.HTTP_200_OK)
        # else:
        #     return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # --- Lógica Manual (Alternativa - Más compleja y propensa a errores) ---
        user_fields_to_update = {}
        profile_fields_to_update = {}
        m2m_fields = {}

        # 1. Separar datos para Usuario, Perfil y M2M
        for key, value in request.data.items():
            if key in ['nombre', 'telefono', 'country', 'gender']:
                user_fields_to_update[key] = value
            elif key in ['bio', 'years_experience', 'therapeutic_approach', 'offers_free_30min_session']:
                # Convertir booleanos de string a boolean
                if key == 'offers_free_30min_session':
                    profile_fields_to_update[key] = value.lower() == 'true'
                # Convertir años a número
                elif key == 'years_experience':
                     try:
                         profile_fields_to_update[key] = int(value) if value else 0
                     except (ValueError, TypeError):
                          return Response({'years_experience': ['Valor inválido.']}, status=status.HTTP_400_BAD_REQUEST)
                else:
                    profile_fields_to_update[key] = value
            elif key == 'specialties':
                m2m_fields['specialties'] = request.data.getlist('specialties') # Usar getlist
            elif key == 'languages':
                m2m_fields['languages'] = request.data.getlist('languages')

        # Manejar archivo de imagen por separado
        if 'profile_pic' in request.FILES:
            # Validar tamaño/tipo aquí si es necesario
            user.profile_pic = request.FILES['profile_pic']
            user_fields_to_update['profile_pic'] = user.profile_pic # Añadir al dict para saber que se actualizó

        # 2. Actualizar Usuario (si hay cambios)
        if user_fields_to_update:
             # Validar con UserSerializer si es necesario
             # user_serializer = UserSerializer(user, data=user_fields_to_update, partial=True)
             # if not user_serializer.is_valid(): return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
             # Actualizar campos directamente
             for attr, value in user_fields_to_update.items():
                 # Evitar actualizar profile_pic aquí si ya se asignó arriba
                 if attr != 'profile_pic':
                      setattr(user, attr, value)
             user.save(update_fields=list(user_fields_to_update.keys()))


        # 3. Actualizar Perfil (si hay cambios o relaciones M2M)
        if profile_fields_to_update or m2m_fields:
            # Validar con PsychologistProfileSerializer si es necesario
            # profile_serializer = PsychologistProfileSerializer(profile, data=profile_fields_to_update, partial=True)
            # if not profile_serializer.is_valid(): return Response(profile_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

             # Actualizar campos simples
             for attr, value in profile_fields_to_update.items():
                  setattr(profile, attr, value)
             if profile_fields_to_update: # Guardar solo si cambiaron campos simples
                 profile.save(update_fields=list(profile_fields_to_update.keys()))

             # Actualizar M2M
             if 'specialties' in m2m_fields:
                 try:
                     specialty_ids = [int(id_str) for id_str in m2m_fields['specialties']]
                     specialties = Specialty.objects.filter(id__in=specialty_ids)
                     profile.specialties.set(specialties)
                 except (ValueError, TypeError):
                     return Response({'specialties': ['IDs inválidos.']}, status=status.HTTP_400_BAD_REQUEST)

             if 'languages' in m2m_fields:
                  try:
                     language_ids = [int(id_str) for id_str in m2m_fields['languages']]
                     languages = Language.objects.filter(id__in=language_ids)
                     profile.languages.set(languages)
                  except (ValueError, TypeError):
                     return Response({'languages': ['IDs inválidos.']}, status=status.HTTP_400_BAD_REQUEST)

        # 4. Devolver respuesta con datos actualizados
        # Re-serializar para obtener el estado final
        final_user_data = UserSerializer(user).data
        final_profile_data = PsychologistProfileSerializer(profile).data
        # Combinar como en la vista GET
        response_data = {
             **final_user_data,
             'bio': final_profile_data.get('bio'),
             'years_experience': final_profile_data.get('years_experience'),
             'therapeutic_approach': final_profile_data.get('therapeutic_approach'),
             'offers_free_30min_session': final_profile_data.get('offers_free_30min_session'),
             'specialties': final_profile_data.get('specialties'),
             'languages': final_profile_data.get('languages'),
        }

        return Response({
            'message': 'Perfil actualizado exitosamente.',
            'profile': response_data # Devolver el perfil combinado actualizado
        }, status=status.HTTP_200_OK)


class SpecialtyListView(ListAPIView):
    """Devuelve la lista de todas las especialidades disponibles."""
    queryset = Specialty.objects.all().order_by('name')
    serializer_class = SpecialtySerializer # Asegúrate que esté importado
    permission_classes = [AllowAny] # Cualquiera puede ver las opciones


class LanguageListView(ListAPIView):
    """Devuelve la lista de todos los idiomas disponibles."""
    queryset = Language.objects.all().order_by('name')
    serializer_class = LanguageSerializer # Asegúrate que esté importado
    permission_classes = [AllowAny]


class MyPatientsListView(APIView):
    """Devuelve la lista de pacientes asignados al psicólogo autenticado."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_psychologist:
            return Response({'error': 'Acceso denegado.'}, status=status.HTTP_403_FORBIDDEN)

        # --- Lógica MEJORADA para obtener pacientes y sus próximas citas ---
        now = timezone.now()

        # Obtener IDs de terapias donde el psicólogo es miembro
        terapia_ids = MiembroTerapia.objects.filter(
            usuario=request.user
        ).values_list('terapia_id', flat=True)

        # Obtener todos los miembros de esas terapias (excluyendo al psicólogo)
        # y prefetch la información del usuario y sus citas futuras
        members = MiembroTerapia.objects.filter(
            terapia_id__in=terapia_ids
        ).exclude(
            usuario=request.user
        ).select_related(
            'usuario' # Cargar datos del modelo Usuario
        ).prefetch_related(
            # Prefetch para las citas futuras de cada paciente con este psicólogo
            # Ajusta el related_name y los filtros según tu modelo CalendarEvent
             Prefetch(
                 'usuario__calendarevent_set', # Asume related_name por defecto para CalendarEvent.participants o un campo 'patient'
                 queryset=CalendarEvent.objects.filter(
                     psychologist=request.user, # Citas con este psicólogo
                     start_time__gte=now
                 ).order_by('start_time'),
                 to_attr='future_appointments_with_psychologist' # Nombre para el atributo prefetch
             )
        ).distinct('usuario') # Evitar duplicados si un paciente está en varias terapias con el mismo psicólogo

        # Construir la respuesta
        patients_data = []
        for member in members:
            patient = member.usuario
            next_appointment = None
            # Acceder a las citas prefetch
            if hasattr(patient, 'future_appointments_with_psychologist') and patient.future_appointments_with_psychologist:
                event = patient.future_appointments_with_psychologist[0] # La primera es la próxima
                next_appointment = {
                      'event_id': event.google_event_id or str(event.id),
                      'title': event.title,
                      'date': event.start_time.isoformat(),
                }

            patients_data.append({
                 'id': patient.id,
                 'name': patient.nombre or patient.email,
                 'next_appointments': [next_appointment] if next_appointment else [] # Devolver lista como en el frontend
             })

        return Response({'patients': patients_data}, status=status.HTTP_200_OK)
    


class GetPsychologistPublicDetailView(RetrieveAPIView):
    """
    Devuelve los detalles públicos de un psicólogo específico.
    Accesible sin autenticación.
    """
    queryset = Usuario.objects.filter(is_psychologist=True).select_related('psychologist_profile').prefetch_related(
         'psychologist_profile__specialties',
         'psychologist_profile__languages',
         # 'psychologist_profile__certifications' # Opcional si lo quieres público
    )
    serializer_class = PsychologistSerializer # Usa el serializer existente o uno específico público si prefieres
    permission_classes = [AllowAny] # <-- PERMITE ACCESO PÚBLICO
    lookup_field = 'pk' # Busca por el ID (primary key) que viene en la URL

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Usuario.DoesNotExist:
             logger.warning(f"Intento de acceso a perfil público de psicólogo inexistente: ID {kwargs.get('pk')}")
             return Response({'error': 'Psicólogo no encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             logger.error(f"Error en GetPsychologistPublicDetailView: {str(e)}", exc_info=True)
             return Response({'error': 'Error interno del servidor'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

# VISTA PARA LISTAR LA DISPONIBILIDAD DEL PSICÓLOGO AUTENTICADO
class MyAvailabilityListView(ListAPIView):
    """
    Devuelve toda la disponibilidad configurada por el psicólogo autenticado.
    """
    serializer_class = AvailabilitySerializer
    permission_classes = [IsAuthenticated] # Requiere autenticación

    def get_queryset(self):
        user = self.request.user
        # Doble verificación: Asegurarse que es un psicólogo
        if not hasattr(user, 'is_psychologist') or not user.is_psychologist:
            logger.warning(f"Usuario no psicólogo {user.email} intentó acceder a MyAvailabilityListView.")
            # Devuelve vacío si no es psicólogo (aunque el permiso debería fallar antes)
            return Availability.objects.none()

        # Filtra la disponibilidad por el usuario (psicólogo) autenticado
        # Ordena para una visualización consistente
        return Availability.objects.filter(psychologist=user).order_by(
            # Ordenar por día de la semana (custom order si es necesario) y luego por hora
            models.Case(
                models.When(day_of_week='Monday', then=models.Value(1)),
                models.When(day_of_week='Tuesday', then=models.Value(2)),
                models.When(day_of_week='Wednesday', then=models.Value(3)),
                models.When(day_of_week='Thursday', then=models.Value(4)),
                models.When(day_of_week='Friday', then=models.Value(5)),
                models.When(day_of_week='Saturday', then=models.Value(6)),
                models.When(day_of_week='Sunday', then=models.Value(7)),
                default=models.Value(8),
                output_field=models.IntegerField(),
            ),
            'start_time'
        )
    
    # --- NUEVA VISTA ---
class PatientSessionChallengesView(APIView):
    """
    Devuelve los retos completados por un paciente específico durante
    el timeframe de una sesión de terapia determinada, accesible solo
    por la psicóloga que condujo la sesión.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, event_id):
        psychologist = request.user

        # 1. Verificar que el usuario es psicólogo
        if not psychologist.is_psychologist:
            return Response(
                {'error': 'Acceso denegado. Se requiere cuenta de psicólogo.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # 2. Obtener el evento de calendario y verificar que pertenece a esta psicóloga
        try:
            # Usamos select_related para obtener el paciente y la terapia eficientemente
            calendar_event = get_object_or_404(
                CalendarEvent.objects.select_related('user', 'terapia'),
                event_id=event_id,       # Buscar por el event_id string
                psychologist=psychologist # Asegurar que la psicóloga sea la solicitante
            )
        except CalendarEvent.DoesNotExist:
             logger.warning(f"Psicóloga {psychologist.email} intentó acceder a retos de evento inexistente o no autorizado: {event_id}")
             return Response({'error': 'Sesión de terapia no encontrada o no tienes permiso para verla.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             logger.error(f"Error buscando CalendarEvent {event_id} para {psychologist.email}: {e}", exc_info=True)
             return Response({'error': 'Error interno al buscar la sesión.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


        # 3. Obtener el paciente de este evento
        patient = calendar_event.user
        if not patient:
             logger.error(f"El evento {event_id} no tiene un usuario (paciente) asociado.")
             return Response({'error': 'La sesión no tiene un paciente asignado.'}, status=status.HTTP_400_BAD_REQUEST)

        # 4. Obtener la terapia del evento (si existe)
        terapia = calendar_event.terapia
        # Descomenta esta validación si los retos SIEMPRE deben estar ligados a una terapia
        # if not terapia:
        #     logger.error(f"El evento {event_id} no tiene una terapia asociada.")
        #     return Response({'error': 'La sesión no está asociada a una terapia específica.'}, status=status.HTTP_400_BAD_REQUEST)


        # 5. Obtener las fechas de inicio y fin del evento
        session_start_time = calendar_event.start_time
        session_end_time = calendar_event.end_time

        # 6. Filtrar los UserChallenge completados por el paciente DENTRO de ese timeframe
        #    y opcionalmente, que pertenezcan a la misma terapia del evento.
        completed_challenges_query = UserChallenge.objects.filter(
            user=patient,
            is_completed=True,
            completed_at__gte=session_start_time, # Completado después o justo al inicio
            completed_at__lte=session_end_time    # Completado antes o justo al final
        ).select_related( # Optimizar incluyendo datos relacionados
            'challenge__category',
            'terapia',
            'collaborative_recipient'
        ).order_by('completed_at') # Ordenar por fecha de finalización

        # --- Filtro Opcional por Terapia ---
        # Si quieres asegurarte de que los retos pertenecen a la MISMA terapia
        # que la sesión del calendario (CalendarEvent), añade este filtro:
        if terapia:
            completed_challenges_query = completed_challenges_query.filter(terapia=terapia)
        else:
            # Si el evento NO tiene terapia, ¿quieres mostrar retos sin terapia
            # completados en ese tiempo? O ninguno? Decide tu lógica.
            # Por ejemplo, para solo mostrar retos sin terapia:
            # completed_challenges_query = completed_challenges_query.filter(terapia__isnull=True)
            # O para no mostrar nada si el evento no tiene terapia:
            completed_challenges_query = completed_challenges_query.none()


        # 7. Serializar los resultados
        # Pasamos el 'request' al contexto por si el serializer lo necesita (ej. presigned URLs)
        serializer = UserChallengeSerializer(completed_challenges_query, many=True, context={'request': request})

        logger.info(f"Psicóloga {psychologist.email} accedió a retos completados por {patient.email} durante sesión {event_id}")
        return Response(serializer.data, status=status.HTTP_200_OK)
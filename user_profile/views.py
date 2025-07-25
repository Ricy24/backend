import logging
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

# Importaciones necesarias
from api.models import Usuario, MiembroTerapia
from dashboard.models import Mood
from dashboard.views import calculate_wellness_days
# Eliminar esta línea
from community.models import Post, Group
from api.serializers import UserSerializer

logger = logging.getLogger(__name__)

class PublicProfileView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, user_id):
        try:
            # Obtener el usuario cuyo perfil se está viendo
            user = get_object_or_404(Usuario, id=user_id)

            # Verificar si el usuario tiene un perfil asociado
            if not hasattr(user, 'profile'):
                logger.warning(f"Usuario {user_id} no tiene un perfil asociado")
                UserProfile.objects.create(user=user)

            # Datos existentes
            wellness_days = calculate_wellness_days(user)
            miembro_terapias = MiembroTerapia.objects.filter(usuario=user).select_related('terapia')
            terapias = [mt.terapia for mt in miembro_terapias]
            therapy_types = list(set(t.tipo for t in terapias))

            therapies_data = []
            for terapia in terapias:
                therapies_data.append({
                    'id': terapia.id,
                    'tipo': terapia.tipo,
                })

            is_own_profile = request.user.is_authenticated and request.user.id == user.id
            posts_data = []  # Lista vacía ya que no usamos más los posts de la comunidad

            # Ensamblar datos del perfil
            response_data = {
                'nombre': user.nombre or '',
                'email': user.email if is_own_profile else None,
                'telefono': user.telefono if is_own_profile else None,
                'wellness_days': wellness_days,
                'therapy_types': therapy_types if therapy_types else [],
                'fecha_registro': user.fecha_registro.isoformat(),
                'therapies': therapies_data,
                'user_posts': posts_data,
                'is_own_profile': is_own_profile,
                'public_likes': user.profile.public_likes,
                'gender': user.gender,
                'birthdate': user.birthdate.isoformat() if user.birthdate else None,
                'country': user.country,
                'is_psychologist': user.is_psychologist,
                'is_new_user': user.is_new_user,
            }
            return Response(response_data, status=status.HTTP_200_OK)

        except Usuario.DoesNotExist:
            logger.error(f"Usuario {user_id} no encontrado")
            return Response({'error': 'Usuario no encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception(f"Error en PublicProfileView para user_id {user_id}: {str(e)}")
            return Response({'error': f'Error interno del servidor: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PrivateProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            # Verificar si el usuario tiene un perfil asociado
            if not hasattr(user, 'profile'):
                logger.warning(f"Usuario {user.id} no tiene un perfil asociado")
                UserProfile.objects.create(user=user)

            wellness_days = calculate_wellness_days(user)
            miembro_terapias = MiembroTerapia.objects.filter(usuario=user).select_related('terapia')
            terapias = [mt.terapia for mt in miembro_terapias]
            therapy_types = list(set(t.tipo for t in terapias))

            therapies_data = []
            for terapia in terapias:
                miembros = MiembroTerapia.objects.filter(terapia=terapia).select_related('usuario')
                shared_moods = []
                if terapia.tipo in ['pareja', 'familiar']:
                    for miembro in miembros:
                        miembro_moods = Mood.objects.filter(user=miembro.usuario).order_by('-timestamp')[:7]
                        shared_moods.extend([
                            {
                                'user_id': miembro.usuario.id,
                                'nombre': miembro.usuario.nombre or miembro.usuario.email,
                                'mood': m.mood,
                                'date': m.timestamp.isoformat(),
                                'description': m.description
                            } for m in miembro_moods
                        ])

                miembros_nombres = [m.usuario.nombre or m.usuario.email for m in miembros]
                herramientas = terapia.herramientas if isinstance(terapia.herramientas, dict) else {}
                herramientas['mood_compartido'] = terapia.tipo in ['pareja', 'familiar']

                therapies_data.append({
                    'id': terapia.id,
                    'tipo': terapia.tipo,
                    'herramientas': herramientas,
                    'miembros_count': miembros.count(),
                    'limite_miembros': terapia.limite_miembros,
                    'shared_moods': shared_moods,
                    'miembros_nombres': miembros_nombres,
                })

            # Posts guardados (comentado porque ya no se usa el área de comunidad)
            saved_posts_data = []

            # Ensamblar datos del perfil
            profile_data = {
                'nombre': user.nombre or '',
                'email': user.email,
                'telefono': user.telefono,
                'wellness_days': wellness_days,
                'therapy_types': therapy_types if therapy_types else [],
                'fecha_registro': user.fecha_registro.isoformat(),
                'therapies': therapies_data,
                'saved_posts': saved_posts_data,
                'user_posts': [],
                'is_own_profile': True,
                'public_likes': user.profile.public_likes,
                'gender': user.gender,
                'birthdate': user.birthdate.isoformat() if user.birthdate else None,
                'country': user.country,
                'is_psychologist': user.is_psychologist,
                'is_new_user': user.is_new_user,
            }
            return Response(profile_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(f"Error en PrivateProfileView para usuario {request.user.id}: {str(e)}")
            return Response({'error': f'Error interno del servidor: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UpdateProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            data = request.data

            # Actualizar solo los campos proporcionados
            if 'nombre' in data:
                user.nombre = data['nombre']
            if 'telefono' in data:
                user.telefono = data['telefono']
            if 'gender' in data:
                user.gender = data['gender']
            if 'birthdate' in data:
                user.birthdate = data['birthdate']
            if 'country' in data:
                user.country = data['country']

            user.save()

            # Devolver los datos actualizados del usuario
            response_data = {
                'nombre': user.nombre or '',
                'email': user.email,
                'telefono': user.telefono,
                'gender': user.gender,
                'birthdate': user.birthdate.isoformat() if user.birthdate else None,
                'country': user.country,
                'is_psychologist': user.is_psychologist,
                'is_new_user': user.is_new_user,
            }
            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(f"Error en UpdateProfileView para usuario {request.user.id}: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
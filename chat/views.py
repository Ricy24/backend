# chat/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q # Importar Q para queries OR
from api.models import Terapia, MiembroTerapia, Usuario # Importar Usuario
from .models import Mensaje, ChatConfig
from .serializers import MensajeSerializer
import logging

logger = logging.getLogger(__name__)

# --- Vista para Mensajes GRUPALES ---
class TerapiaMensajesGrupalesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, terapia_id):
        # Verificar membresía y si el chat está habilitado
        try:
            miembro = MiembroTerapia.objects.select_related('terapia__chat_config').get(
                usuario=request.user, terapia_id=terapia_id
            )
            if not miembro.terapia.chat_config.chat_habilitado:
                return Response({'error': 'El chat no está habilitado para esta terapia'}, status=status.HTTP_403_FORBIDDEN)
        except MiembroTerapia.DoesNotExist:
            return Response({'error': 'No eres miembro de esta terapia'}, status=status.HTTP_403_FORBIDDEN)
        except ChatConfig.DoesNotExist:
             return Response({'error': 'Configuración de chat no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             logger.error(f"Error verificando acceso chat grupal {terapia_id} por {request.user.email}: {e}", exc_info=True)
             return Response({'error': 'Error al verificar acceso al chat'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Obtener solo mensajes grupales (recipient es NULL)
        mensajes = Mensaje.objects.filter(
            terapia=miembro.terapia,
            recipient__isnull=True # La clave para mensajes grupales
        ).select_related('usuario').order_by('timestamp') # Optimizar query

        serializer = MensajeSerializer(mensajes, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

# --- Vista para enviar mensajes (GRUPALES o PRIVADOS) ---
class EnviarMensajeTerapiaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, terapia_id):
        # Verificar membresía y si el chat está habilitado (similar a GET)
        try:
            miembro = MiembroTerapia.objects.select_related('terapia__chat_config').get(
                usuario=request.user, terapia_id=terapia_id
            )
            if not miembro.terapia.chat_config.chat_habilitado:
                return Response({'error': 'El chat no está habilitado para esta terapia'}, status=status.HTTP_403_FORBIDDEN)
        except MiembroTerapia.DoesNotExist:
            return Response({'error': 'No eres miembro de esta terapia'}, status=status.HTTP_403_FORBIDDEN)
        except ChatConfig.DoesNotExist:
             return Response({'error': 'Configuración de chat no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             logger.error(f"Error verificando acceso envío {terapia_id} por {request.user.email}: {e}", exc_info=True)
             return Response({'error': 'Error al verificar acceso para enviar'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Usar el serializer para validar y crear
        serializer = MensajeSerializer(
            data=request.data,
            context={'request': request, 'terapia_id': terapia_id} # Pasar contexto
        )
        if serializer.is_valid():
            # El serializer valida recipient_id si se proporciona
            recipient_id = serializer.validated_data.get('recipient_id')
            recipient_user = None
            if recipient_id:
                 # El validador ya comprobó que existe y es miembro
                 recipient_user = Usuario.objects.get(id=recipient_id)
                 # Asegurarse de no enviarse a sí mismo un mensaje privado
                 if recipient_user == request.user:
                      return Response({'error': 'No puedes enviarte un mensaje privado a ti mismo.'}, status=status.HTTP_400_BAD_REQUEST)

            # Crear el mensaje asignando usuario y terapia manualmente
            mensaje = serializer.save(
                usuario=request.user,
                terapia=miembro.terapia,
                recipient=recipient_user # Asignar destinatario si es privado
            )
            # Devolver el mensaje recién creado (ya serializado)
            response_serializer = MensajeSerializer(mensaje) # Serializar de nuevo para incluir campos read-only
            log_msg = f"Mensaje {'privado a ' + recipient_user.email if recipient_user else 'grupal'} enviado en terapia {terapia_id} por {request.user.email}"
            logger.info(log_msg)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        else:
            logger.warning(f"Error de validación al enviar mensaje en terapia {terapia_id} por {request.user.email}: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# --- Vista para obtener Mensajes PRIVADOS ---
class TerapiaMensajesPrivadosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, terapia_id, other_user_id):
        # Verificar membresía y si el chat está habilitado (similar a GET grupal)
        try:
            miembro_actual = MiembroTerapia.objects.select_related('terapia__chat_config').get(
                usuario=request.user, terapia_id=terapia_id
            )
            if not miembro_actual.terapia.chat_config.chat_habilitado:
                return Response({'error': 'El chat no está habilitado para esta terapia'}, status=status.HTTP_403_FORBIDDEN)

            # Verificar que el otro usuario exista y sea miembro de la misma terapia
            otro_miembro = get_object_or_404(
                 MiembroTerapia,
                 usuario_id=other_user_id,
                 terapia=miembro_actual.terapia # Asegura que sea de la misma terapia
            )
        except MiembroTerapia.DoesNotExist:
            return Response({'error': 'No eres miembro o el otro usuario no pertenece a esta terapia'}, status=status.HTTP_403_FORBIDDEN)
        except ChatConfig.DoesNotExist:
             return Response({'error': 'Configuración de chat no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
             logger.error(f"Error verificando acceso chat privado {terapia_id} entre {request.user.id} y {other_user_id}: {e}", exc_info=True)
             return Response({'error': 'Error al verificar acceso al chat privado'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Obtener mensajes donde el usuario actual es remitente y el otro es destinatario,
        # O viceversa, dentro de la terapia actual.
        mensajes = Mensaje.objects.filter(
            Q(terapia=miembro_actual.terapia) &
            (
                (Q(usuario=request.user) & Q(recipient=otro_miembro.usuario)) |
                (Q(usuario=otro_miembro.usuario) & Q(recipient=request.user))
            )
        ).select_related('usuario', 'recipient').order_by('timestamp') # Optimizar

        serializer = MensajeSerializer(mensajes, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# --- Vista para Eliminar Mensajes (sin cambios, ya maneja permisos) ---
class EliminarMensajeTerapiaView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, terapia_id, mensaje_id):
        # (Tu código existente aquí está probablemente bien,
        #  ya que verifica si el usuario es el dueño o el líder)
        # ... (Tu código actual para eliminar) ...
        # Asegúrate de que las excepciones y logs son adecuados
        try:
            miembro = get_object_or_404(
                MiembroTerapia.objects.select_related('terapia__chat_config'), # Incluir chat_config
                usuario=request.user,
                terapia__id=terapia_id
            )
            # Re-chequear config por si acaso
            if not miembro.terapia.chat_config.chat_habilitado:
                return Response({'error': 'El chat no está habilitado'}, status=status.HTTP_403_FORBIDDEN)

            mensaje = get_object_or_404(
                Mensaje,
                id=mensaje_id,
                terapia=miembro.terapia # Asegura que el mensaje sea de esta terapia
            )

            # Verificar permiso: O eres el dueño del mensaje O eres líder de la terapia
            es_lider = miembro.es_lider

            if mensaje.usuario != request.user and not es_lider:
                logger.warning(f"Intento no autorizado de eliminar mensaje {mensaje_id} por {request.user.email} (no es dueño ni líder)")
                return Response(
                    {'error': 'No tienes permiso para eliminar este mensaje'},
                    status=status.HTTP_403_FORBIDDEN
                )

            mensaje_contenido = mensaje.contenido[:30] # Guardar para log antes de borrar
            mensaje.delete()
            logger.info(f"Mensaje {mensaje_id} ('{mensaje_contenido}...') eliminado en terapia {terapia_id} por {request.user.email}")
            return Response({'message': 'Mensaje eliminado'}, status=status.HTTP_204_NO_CONTENT)

        except MiembroTerapia.DoesNotExist:
             return Response({'error': 'No eres miembro de esta terapia'}, status=status.HTTP_403_FORBIDDEN)
        except Mensaje.DoesNotExist:
             return Response({'error': 'Mensaje no encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except ChatConfig.DoesNotExist: # Aunque ya se chequeó arriba
             return Response({'error': 'Configuración de chat no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error en EliminarMensajeTerapiaView ({terapia_id}, {mensaje_id}): {str(e)}", exc_info=True)
            return Response({'error': 'Error interno al eliminar el mensaje'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
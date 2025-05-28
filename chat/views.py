# chat/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q # Importar Q para queries OR
from api.models import Terapia, MiembroTerapia, Usuario # Importar Usuario
from .models import Mensaje, ChatConfig, CoachingSession, CoachingMensaje, CoachingMeta
from .serializers import MensajeSerializer,    CoachingSessionSerializer,CoachingMensajeSerializer,CoachingMetaSerializer
import logging
from .services import GroqCoachingService

logger = logging.getLogger(__name__)

class IniciarCoachingSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Un usuario solo puede tener una sesión de coaching activa a la vez (OneToOneField)
        # O podrías permitir múltiples si cambias el OneToOneField a ForeignKey y manejas la "activa"
        sesion_existente = CoachingSession.objects.filter(usuario=request.user).first()
        if sesion_existente:
            serializer = CoachingSessionSerializer(sesion_existente)
            return Response({
                "message": "Ya tienes una sesión de coaching. Aquí están los detalles.",
                "sesion": serializer.data
            }, status=status.HTTP_200_OK)

        serializer = CoachingSessionSerializer(data=request.data)
        if serializer.is_valid():
            # Asignar el usuario actual a la sesión
            serializer.save(usuario=request.user)
            logger.info(f"Sesión de coaching iniciada para {request.user.email} con objetivo: {serializer.data.get('objetivo_principal')}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        logger.warning(f"Error al iniciar sesión de coaching para {request.user.email}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CoachingSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sesion = get_object_or_404(CoachingSession, usuario=request.user)
        serializer = CoachingSessionSerializer(sesion)
        return Response(serializer.data)

    def put(self, request): # Para actualizar el objetivo principal
        sesion = get_object_or_404(CoachingSession, usuario=request.user)
        serializer = CoachingSessionSerializer(sesion, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Sesión de coaching actualizada para {request.user.email}.")
            return Response(serializer.data)
        logger.warning(f"Error al actualizar sesión de coaching para {request.user.email}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request): # Para terminar una sesión
        sesion = get_object_or_404(CoachingSession, usuario=request.user)
        sesion.delete()
        logger.info(f"Sesión de coaching eliminada para {request.user.email}.")
        return Response(status=status.HTTP_204_NO_CONTENT)


class EnviarMensajeCoachingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sesion_coaching = get_object_or_404(CoachingSession, usuario=request.user)
        contenido_usuario = request.data.get('contenido')

        if not contenido_usuario:
            return Response({'error': 'El contenido del mensaje no puede estar vacío.'}, status=status.HTTP_400_BAD_REQUEST)

        # Aquí es donde llamas a tu servicio de Groq
        # El servicio se encargará de guardar el mensaje del usuario y la respuesta de la IA
        groq_service = GroqCoachingService()
        mensaje_ia = groq_service.obtener_respuesta_coach(sesion_coaching, contenido_usuario)

        # Serializar y devolver la respuesta de la IA (o ambos mensajes si prefieres)
        serializer_ia = CoachingMensajeSerializer(mensaje_ia)
        
        # Opcional: si quieres devolver también el mensaje del usuario
        # mensaje_usuario_obj = CoachingMensaje.objects.filter(sesion=sesion_coaching, es_respuesta_ia=False).latest('timestamp')
        # serializer_usuario = CoachingMensajeSerializer(mensaje_usuario_obj)
        # return Response({
        #     "mensaje_usuario": serializer_usuario.data,
        #     "respuesta_ia": serializer_ia.data
        # }, status=status.HTTP_201_CREATED)

        logger.info(f"Mensaje de IA enviado en coaching para {request.user.email}.")
        return Response(serializer_ia.data, status=status.HTTP_201_CREATED)


class CoachingMensajesListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sesion_coaching = get_object_or_404(CoachingSession, usuario=request.user)
        mensajes = CoachingMensaje.objects.filter(sesion=sesion_coaching).order_by('timestamp')
        serializer = CoachingMensajeSerializer(mensajes, many=True)
        return Response(serializer.data)

# --- Vistas para Metas de Coaching (Opcional pero recomendado) ---
class CoachingMetaListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sesion = get_object_or_404(CoachingSession, usuario=request.user)
        metas = CoachingMeta.objects.filter(sesion=sesion)
        serializer = CoachingMetaSerializer(metas, many=True)
        return Response(serializer.data)

    def post(self, request):
        sesion = get_object_or_404(CoachingSession, usuario=request.user)
        serializer = CoachingMetaSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(sesion=sesion) # Asigna la sesión actual
            logger.info(f"Nueva meta de coaching creada para {request.user.email}: {serializer.data.get('descripcion')}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        logger.warning(f"Error al crear meta de coaching para {request.user.email}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CoachingMetaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_meta(self, request, meta_id):
        sesion = get_object_or_404(CoachingSession, usuario=request.user)
        return get_object_or_404(CoachingMeta, id=meta_id, sesion=sesion)

    def get(self, request, meta_id):
        meta = self.get_meta(request, meta_id)
        serializer = CoachingMetaSerializer(meta)
        return Response(serializer.data)

    def put(self, request, meta_id):
        meta = self.get_meta(request, meta_id)
        serializer = CoachingMetaSerializer(meta, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Meta de coaching {meta_id} actualizada para {request.user.email}.")
            return Response(serializer.data)
        logger.warning(f"Error al actualizar meta de coaching {meta_id} para {request.user.email}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, meta_id):
        meta = self.get_meta(request, meta_id)
        meta.delete()
        logger.info(f"Meta de coaching {meta_id} eliminada para {request.user.email}.")
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConfirmarSubMetaCoachingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sesion_coaching = get_object_or_404(CoachingSession, usuario=request.user)
        
        descripcion_sub_meta = request.data.get('descripcion_sub_meta')
        aceptada = request.data.get('aceptada') # boolean
        tool_call_id_original = request.data.get('tool_call_id') # Opcional

        if descripcion_sub_meta is None or aceptada is None:
            return Response(
                {'error': 'Faltan datos: descripcion_sub_meta y aceptada son requeridos.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        groq_service = GroqCoachingService()
        mensaje_respuesta_ia = groq_service.confirmar_creacion_sub_meta(
            sesion_coaching,
            descripcion_sub_meta,
            bool(aceptada), # Asegurar que sea booleano
            tool_call_id_original 
        )
        
        serializer_ia = CoachingMensajeSerializer(mensaje_respuesta_ia)
        
        # Podrías querer devolver también la lista actualizada de metas si aceptada es true
        # metas_actualizadas = CoachingMeta.objects.filter(sesion=sesion_coaching, completada=False)
        # serializer_metas = CoachingMetaSerializer(metas_actualizadas, many=True)
        
        return Response({
            "respuesta_ia": serializer_ia.data,
            # "metas_actualizadas": serializer_metas.data if bool(aceptada) else [] 
        }, status=status.HTTP_200_OK)
    

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
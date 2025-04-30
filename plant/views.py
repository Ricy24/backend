from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny  # Agregamos AllowAny aquí
from .models import Plant
from api.models import Terapia, MiembroTerapia
from .serializers import PlantSerializer


import logging

logger = logging.getLogger(__name__)

class PlantDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, terapia_id):
        """Obtener los detalles de la planta asociada a la terapia."""
        logger.info(f"Solicitud GET recibida para terapia_id: {terapia_id}")
        try:
            terapia = Terapia.objects.get(id=terapia_id)
            if not MiembroTerapia.objects.filter(usuario=request.user, terapia=terapia).exists():
                logger.warning(f"Usuario {request.user} no es miembro de la terapia {terapia_id}")
                return Response(
                    {'error': 'No eres miembro de esta terapia'},
                    status=status.HTTP_403_FORBIDDEN
                )
            plant = Plant.objects.get(terapia=terapia)
            serializer = PlantSerializer(plant)
            logger.info(f"Planta encontrada para terapia {terapia_id}: {serializer.data}")
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Terapia.DoesNotExist:
            logger.error(f"Terapia {terapia_id} no encontrada")
            return Response({'error': 'Terapia no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Plant.DoesNotExist:
            logger.info(f"No hay planta asociada a la terapia {terapia_id}")
            return Response(
                {'message': 'No hay planta asociada a esta terapia aún'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error obteniendo planta: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request, terapia_id):
        """Crear o actualizar la planta asociada a la terapia."""
        logger.info(f"Solicitud POST recibida para terapia_id: {terapia_id}")
        try:
            terapia = Terapia.objects.get(id=terapia_id)
            logger.info(f"Terapia encontrada: {terapia.id}")
            if not MiembroTerapia.objects.filter(usuario=request.user, terapia=terapia, es_lider=True).exists():
                logger.warning(f"Usuario {request.user} no es líder de la terapia {terapia_id}")
                return Response(
                    {'error': 'Solo el líder puede seleccionar la planta'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            plant_type = request.data.get('plant_type')
            if not plant_type:
                logger.error("Falta el campo 'plant_type' en los datos enviados")
                return Response(
                    {'error': 'El tipo de planta es requerido'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            plant, created = Plant.objects.get_or_create(
                terapia=terapia,
                defaults={
                    'type': 'arbol' if terapia.tipo == 'familiar' else 'planta',
                    'design': plant_type,
                    'name': 'Planta sin nombre',
                    'level': 1,
                    'current_streak': 0,
                }
            )
            if not created:
                plant.design = plant_type
                plant.save()
            
            serializer = PlantSerializer(plant)
            logger.info(f"Planta seleccionada para terapia {terapia_id}: {serializer.data}")
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Terapia.DoesNotExist:
            logger.error(f"Terapia {terapia_id} no encontrada")
            return Response({'error': 'Terapia no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error seleccionando planta: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CarePlantView(APIView):
    """Registrar una acción de cuidado para la planta."""
    permission_classes = [IsAuthenticated]

    def post(self, request, terapia_id):
        try:
            terapia = Terapia.objects.get(id=terapia_id)
            if not MiembroTerapia.objects.filter(usuario=request.user, terapia=terapia).exists():
                return Response({'error': 'No eres miembro de esta terapia'}, status=status.HTTP_403_FORBIDDEN)
            
            plant = Plant.objects.get(terapia=terapia)
            if plant.care(request.user):
                return Response(
                    {
                        'message': 'Planta cuidada exitosamente',
                        'level': plant.level,
                        'streak': plant.current_streak
                    },
                    status=status.HTTP_200_OK
                )
            else:
                return Response({'error': 'Ya has cuidado la planta hoy'}, status=status.HTTP_400_BAD_REQUEST)
        except Terapia.DoesNotExist:
            return Response({'error': 'Terapia no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Plant.DoesNotExist:
            return Response({'error': 'Planta no encontrada para esta terapia'}, status=status.HTTP_404_NOT_FOUND)

class CustomizePlantView(APIView):
    """Personalizar el nombre de la planta (solo el líder)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, terapia_id):
        try:
            terapia = Terapia.objects.get(id=terapia_id)
            if not MiembroTerapia.objects.filter(usuario=request.user, terapia=terapia, es_lider=True).exists():
                return Response({'error': 'Solo el líder puede personalizar la planta'}, status=status.HTTP_403_FORBIDDEN)
            
            plant = Plant.objects.get(terapia=terapia)
            name = request.data.get('name')
            if name:
                plant.name = name
                plant.save()
                return Response(
                    {'message': 'Planta personalizada exitosamente', 'name': plant.name},
                    status=status.HTTP_200_OK
                )
            return Response({'error': 'Nombre es requerido'}, status=status.HTTP_400_BAD_REQUEST)
        except Terapia.DoesNotExist:
            return Response({'error': 'Terapia no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Plant.DoesNotExist:
            return Response({'error': 'Planta no encontrada para esta terapia'}, status=status.HTTP_404_NOT_FOUND)

class PublicPlantView(APIView):
    permission_classes = [AllowAny]  # Sin autenticación requerida

    def get(self, request, terapia_id):
        try:
            terapia = Terapia.objects.get(id=terapia_id)
            plant = Plant.objects.get(terapia=terapia)
            # Devolver solo datos públicos
            data = {
                'name': plant.name,
                'type': plant.type,
                'level': plant.level,
                'design': plant.design,
            }
            return Response(data, status=status.HTTP_200_OK)
        except Terapia.DoesNotExist:
            return Response({'error': 'Terapia no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Plant.DoesNotExist:
            return Response({'message': 'No hay planta asociada'}, status=status.HTTP_404_NOT_FOUND)
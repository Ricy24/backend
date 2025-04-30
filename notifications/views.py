from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import Notification
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            notifications = Notification.objects.filter(recipient=user).order_by('-created_at')
            data = [
                {
                    'id': notif.id,
                    'type': notif.notification_type,
                    'message': notif.message,
                    'created_at': notif.created_at.isoformat(),
                    'is_read': notif.is_read,
                    'related_object_id': notif.related_object_id,
                }
                for notif in notifications
            ]
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en NotificationListView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class MarkNotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        try:
            notification = Notification.objects.get(id=notification_id, recipient=request.user)
            notification.is_read = True
            notification.save()
            return Response({'message': 'Notificación marcada como leída'}, status=status.HTTP_200_OK)
        except Notification.DoesNotExist:
            return Response({'error': 'Notificación no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error en MarkNotificationReadView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
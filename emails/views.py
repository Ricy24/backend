from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
# --- Elimina las importaciones de Brevo si ya no se usan ---
# import sib_api_v3_sdk
# from sib_api_v3_sdk.rest import ApiException
# ----------------------------------------------------------
# from django.template.loader import render_to_string # Ya no se necesita aquí si está en utils
import uuid
from datetime import timedelta
import logging

# --- ¡IMPORTANTE! Importa la función desde utils.py ---
from .utils import send_brevo_email
# -----------------------------------------------------

User = get_user_model()
logger = logging.getLogger(__name__)



class SendWelcomeEmailView(APIView):
    permission_classes = [AllowAny]  # Permitido internamente desde el registro

    def post(self, request):
        email = request.data.get('email')
        nombre = request.data.get('nombre', 'Usuario')

        if not email:
            return Response({'error': 'El email es obligatorio'}, status=status.HTTP_400_BAD_REQUEST)

        context = {
            'nombre': nombre,
            'dashboard_url': f"{settings.FRONTEND_URL}/dashboard",
            'year': timezone.now().year,
        }

        # Ahora esta llamada usará la función importada de utils.py
        success = send_brevo_email(
            subject="¡Bienvenid@ a Senti!", # Asegúrate que el asunto sea el correcto
            to_email=email,
            template_name="welcome_email.html", # Revisa el nombre del template
            context=context
        )

        if success:
            return Response({'message': 'Correo de bienvenida enviado'}, status=status.HTTP_200_OK)
        # El logger en utils.py ya registrará el error detallado si falla
        return Response({'error': 'Error al enviar el correo'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')

        if not email:
            return Response({'error': 'El email es obligatorio'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'error': 'No existe un usuario con este email'}, status=status.HTTP_404_NOT_FOUND)

        # Generar token de restablecimiento
        reset_token = str(uuid.uuid4())
        user.reset_token = reset_token
        user.reset_token_expiry = timezone.now() + timedelta(hours=2)  # Expira en 2 horas
        user.save()

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"

        context = {
            'nombre': user.nombre or user.email.split('@')[0],
            'reset_url': reset_url,
            'expire_hours': 2,
            'year': timezone.now().year,
        }

        success = send_brevo_email(
            subject="Restablece tu contraseña - SentiBien",
            to_email=email,
            template_name="reset_password_email.html",
            context=context
        )

        if success:
            logger.info(f"Solicitud de restablecimiento enviada a {email}")
            return Response({'message': 'Correo de restablecimiento enviado'}, status=status.HTTP_200_OK)
        return Response({'error': 'Error al enviar el correo'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        new_password = request.data.get('new_password')

        if not token or not new_password:
            return Response({'error': 'Token y nueva contraseña son obligatorios'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(reset_token=token)
            if user.reset_token_expiry < timezone.now():
                return Response({'error': 'El token ha expirado'}, status=status.HTTP_400_BAD_REQUEST)

            if len(new_password) < 8:
                return Response({'error': 'La contraseña debe tener al menos 8 caracteres'}, status=status.HTTP_400_BAD_REQUEST)

            user.set_password(new_password)
            user.reset_token = None
            user.reset_token_expiry = None
            user.save()

            logger.info(f"Contraseña restablecida para {user.email}")
            return Response({'message': 'Contraseña restablecida con éxito'}, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({'error': 'Token inválido'}, status=status.HTTP_400_BAD_REQUEST)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
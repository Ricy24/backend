from django.conf import settings
from django.contrib.auth import get_user_model  # Importamos get_user_model
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Invitation, Reward
from .serializers import InvitationSerializer, RewardSerializer, UserSerializer
import datetime

# Vista para invitar a un amigo
class InviteFriendView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = InvitationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = serializer.save(inviter=self.request.user)
        invite_link = f"{settings.FRONTEND_URL}/auth?invite_code={invitation.invite_code}"
        return Response({
            "message": "Enlace de invitación generado",
            "invite_link": invite_link
        }, status=status.HTTP_201_CREATED)

# Vista para aceptar una invitación
class AcceptInvitationView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        invite_code = request.data.get('invite_code')
        try:
            invitation = Invitation.objects.get(invite_code=invite_code, is_accepted=False)
            invitation.invitee = request.user  # Asociar al usuario que acepta
            invitation.is_accepted = True
            invitation.accepted_at = datetime.datetime.now()
            invitation.save()

            # Otorgar 10 puntos al invitador
            Reward.objects.create(
                user=invitation.inviter,
                description="Invitación aceptada: 10 puntos",
                points=10
            )

            return Response({"message": "Invitación aceptada, recompensa otorgada al invitador"}, status=status.HTTP_200_OK)
        except Invitation.DoesNotExist:
            return Response({"error": "Código de invitación inválido o ya usado"}, status=status.HTTP_400_BAD_REQUEST)

# Vista para listar las recompensas del usuario
class UserRewardsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RewardSerializer

    def get_queryset(self):
        return Reward.objects.filter(user=self.request.user)

# Vista para listar los usuarios invitados que aceptaron
class InvitedUsersView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_queryset(self):
        User = get_user_model()  # Obtenemos el modelo de usuario real
        return User.objects.filter(
            received_invitations__inviter=self.request.user,
            received_invitations__is_accepted=True
        )
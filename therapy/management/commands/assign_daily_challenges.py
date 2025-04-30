# therapy/management/commands/assign_daily_challenges.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from therapy.models import EmotionalPath, Challenge, UserChallenge, UserPathProgress
from api.models import Terapia, MiembroTerapia
from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Asigna retos diarios a todos los usuarios con rutas emocionales activas.'

    def handle(self, *args, **kwargs):
        today = timezone.now().date()
        users = set(EmotionalPath.objects.filter(is_active=True).values_list('user', flat=True))

        for user_id in users:
            try:
                user = User.objects.get(id=user_id)
                terapias = Terapia.objects.filter(miembros__usuario=user)
                for terapia in terapias or [None]:
                    self.assign_daily_challenge(user, terapia, today)
            except Exception as e:
                logger.error(f"Error asignando reto para usuario {user_id}: {str(e)}")
                continue

        self.stdout.write(self.style.SUCCESS('Retos diarios asignados exitosamente.'))

    def assign_daily_challenge(self, user, terapia, today):
        """
        Asigna un reto diario para un usuario y terapia.
        """
        # Verificar si ya tiene un reto hoy
        if UserChallenge.objects.filter(
            user=user, terapia=terapia, assigned_at__date=today, is_completed=False
        ).exists():
            logger.info(f"Usuario {user.email} ya tiene reto para {today} (terapia: {terapia.id if terapia else 'ninguna'})")
            return

        # Obtener rutas activas
        paths = EmotionalPath.objects.filter(user=user, terapia=terapia, is_active=True)
        if not paths:
            logger.info(f"Usuario {user.email} no tiene rutas activas (terapia: {terapia.id if terapia else 'ninguna'})")
            return

        progress, _ = UserPathProgress.objects.get_or_create(
            user=user, terapia=terapia, defaults={'current_level': 1}
        )
        current_level = progress.current_level

        # Obtener categorías de rutas activas
        categories = paths.values_list('category', flat=True)

        # Obtener categorías usadas recientemente
        last_assignments = UserChallenge.objects.filter(
            user=user, terapia=terapia, assigned_at__gte=today - timedelta(days=len(categories))
        ).order_by('-assigned_at').values_list('challenge__category', flat=True)
        used_categories = list(last_assignments)[:len(categories)]

        # Elegir una categoría no usada recientemente
        available_categories = [c for c in categories if c not in used_categories]
        if not available_categories:
            available_categories = list(categories)

        # Seleccionar un reto no completado
        completed_challenges = UserChallenge.objects.filter(
            user=user, terapia=terapia, is_completed=True
        ).values_list('challenge', flat=True)

        challenge = Challenge.objects.filter(
            category__in=available_categories,
            level=current_level
        ).exclude(id__in=completed_challenges).order_by('?').first()

        if not challenge:
            logger.warning(f"No hay retos disponibles para {user.email} en nivel {current_level}")
            return

        # Asignar reto
        user_challenge = UserChallenge.objects.create(
            user=user,
            terapia=terapia,
            challenge=challenge
        )

        # Si es colaborativo, asignar destinatario
        if challenge.mode_collaborative and terapia:
            members = MiembroTerapia.objects.filter(terapia=terapia).exclude(usuario=user)
            if members:
                recipient = members.first().usuario
                user_challenge.collaborative_recipient = recipient
                user_challenge.save()
                # Enviar mensaje por chat
                message_content = (
                    f"Hola {recipient.email}, te he invitado a realizar un reto colaborativo: "
                    f"'{challenge.title}'. {challenge.description} ¡Vamos a hacerlo juntos!"
                )
                Mensaje.objects.create(
                    terapia=terapia,
                    usuario=user,
                    contenido=message_content
                )

        logger.info(f"Reto '{challenge.title}' asignado a {user.email} para {today}")
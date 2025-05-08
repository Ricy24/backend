# therapy/tasks.py
from django.utils import timezone
from django.contrib.auth import get_user_model
from celery import shared_task
from .models import (
    EmotionalPath,
    Challenge,
    UserChallenge,
    UserPathProgress,
    # EmotionalProfile ya no se usa directamente aquí para la asignación,
    # se infiere a través del usuario y su progreso/rutas.
    # Category se usa indirectamente a través de EmotionalPath y Challenge.
)
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task
# Esta tarea es la que se llama desde Celery Beat
# (según tu celery.py: 'task': 'therapy.tasks.assign_daily_challenges')
def assign_daily_challenges():
    """
    Asigna un reto diario a cada usuario activo que tenga un UserPathProgress
    y rutas emocionales activas, si aún no tiene uno asignado para hoy.
    """
    today = timezone.localtime(timezone.now()).date()
    
    # Iterar sobre todos los usuarios que podrían necesitar un reto.
    # Podrías filtrar más aquí si solo quieres usuarios activos, con suscripción, etc.
    for user in User.objects.filter(is_active=True): # Iterar sobre usuarios activos
        try:
            # Obtener el progreso del usuario. Asumimos que cada usuario puede tener múltiples
            # UserPathProgress si está en múltiples terapias. Debemos iterar sobre ellos.
            # O si un usuario solo tiene un UserPathProgress global, ajusta esto.
            # Por ahora, asumiré que queremos asignar retos para CADA UserPathProgress activo.
            
            user_progress_entries = UserPathProgress.objects.filter(user=user)
            if not user_progress_entries.exists():
                # logger.debug(f"Usuario {user.email} no tiene UserPathProgress. Saltando.")
                continue

            for progress in user_progress_entries:
                terapia = progress.terapia # Puede ser None si el progreso no está ligado a una terapia específica
                current_level = progress.current_level

                # Verificar si ya se asignó un reto para este usuario, esta terapia (si existe) y para hoy
                challenge_already_assigned_today = UserChallenge.objects.filter(
                    user=user,
                    terapia=terapia, # Importante filtrar por la misma terapia (o None)
                    available_date=today
                ).exists()

                if challenge_already_assigned_today:
                    # logger.debug(f"Reto ya asignado hoy para {user.email} en terapia {terapia.id if terapia else 'global'}. Saltando.")
                    continue

                # Obtener las categorías activas para este usuario, terapia y nivel
                active_paths = EmotionalPath.objects.filter(
                    user=user,
                    terapia=terapia, # Coincidir con la terapia del UserPathProgress
                    is_active=True,
                    level=current_level # Solo categorías del nivel actual del progreso
                )

                if not active_paths.exists():
                    # logger.debug(f"Usuario {user.email} no tiene EmotionalPath activo para terapia {terapia.id if terapia else 'global'} nivel {current_level}. Saltando.")
                    continue
                
                active_category_ids = list(active_paths.values_list('category_id', flat=True))

                # Obtener IDs de TODOS los retos YA ASIGNADOS (completados o no) al usuario en ESTA terapia/nivel
                assigned_challenge_ids_for_level = UserChallenge.objects.filter(
                    user=user,
                    terapia=terapia,
                    challenge__level=current_level # Solo considerar retos ya asignados de este nivel
                ).values_list('challenge_id', flat=True).distinct()
                
                # Buscar retos candidatos:
                # - De las categorías activas del usuario
                # - Del nivel actual del usuario
                # - Que NO hayan sido asignados previamente en este nivel y terapia
                assignable_challenges = Challenge.objects.filter(
                    category_id__in=active_category_ids,
                    level=current_level
                ).exclude(
                    id__in=assigned_challenge_ids_for_level
                )

                if not assignable_challenges.exists():
                    logger.warning(f"No hay nuevos retos disponibles para {user.email} en terapia {terapia.id if terapia else 'global'}, nivel {current_level}, categorías {active_category_ids}.")
                    # Aquí podrías tener lógica para "resetear" retos si se completaron todos los de un nivel,
                    # o notificar que no hay más contenido, o avanzar de nivel si se completaron todos.
                    # Por ahora, simplemente no asignamos nada.
                    continue

                # Seleccionar un reto de los candidatos (aleatorio)
                challenge_to_assign = assignable_challenges.order_by('?').first()

                if challenge_to_assign:
                    # Crear la instancia del reto para el usuario
                    user_challenge_instance = UserChallenge.objects.create(
                        user=user,
                        terapia=terapia, # Asociar con la terapia del progreso
                        challenge=challenge_to_assign,
                        available_date=today,
                        assigned_at=timezone.now(), # Marcar cuándo se asignó
                        is_completed=False
                    )
                    logger.info(f"Reto '{challenge_to_assign.title}' (UC ID: {user_challenge_instance.id}) asignado a {user.email} para terapia '{terapia.id if terapia else 'Global'}' en fecha {today}.")
                else:
                    # Este caso es cubierto por el `if not assignable_challenges.exists():` de arriba
                    # pero lo mantenemos por si la lógica cambia.
                    logger.warning(f"No se pudo seleccionar un reto específico para {user.email} en terapia {terapia.id if terapia else 'global'} nivel {current_level} (esto no debería pasar si assignable_challenges existe).")

        except Exception as e:
            logger.error(f"Error procesando asignación de reto para {user.email}: {str(e)}", exc_info=True)
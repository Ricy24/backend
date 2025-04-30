# therapy/tasks.py
from django.utils import timezone
from .models import EmotionalProfile, Challenge, ChallengeInstance, ProfileCategory
import logging

logger = logging.getLogger(__name__)

def assign_daily_challenges():
    """Assign daily challenges to users, rotating between selected categories."""
    today = timezone.now().date()
    for profile in EmotionalProfile.objects.all():
        try:
            # Obtener categorías del perfil, ordenadas por prioridad
            categories = profile.profilecategory_set.order_by('priority')
            if not categories.exists():
                logger.warning(f"No categories for profile {profile.user.email}")
                continue

            # Calcular qué categoría toca hoy (rotación cíclica)
            day_offset = (today - profile.created_at.date()).days
            category_index = day_offset % categories.count()
            selected_category = categories[category_index].category
            current_level = categories[category_index].current_level

            # Seleccionar un reto para la categoría y nivel
            challenge = Challenge.objects.filter(
                category=selected_category,
                level=current_level
            ).first()

            if not challenge:
                logger.warning(f"No challenge found for {selected_category.name}, level {current_level} for {profile.user.email}")
                continue

            # Crear instancia de reto
            instance = ChallengeInstance.objects.create(
                challenge=challenge,
                terapia=profile.terapia,
                assigned_date=today,
                completed_by_all=False
            )
            instance.users.add(profile.user)
            logger.info(f"Assigned challenge {challenge.title} to {profile.user.email} for {today}")
        except Exception as e:
            logger.error(f"Error assigning challenge for {profile.user.email}: {str(e)}", exc_info=True)
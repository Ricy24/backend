import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from dashboard.models import WellnessGoal as OldWellnessGoal
from api.models import WellnessGoal as NewWellnessGoal
from therapy.models import Challenge

# Migrar WellnessGoal
old_goals = OldWellnessGoal.objects.all()
for old_goal in old_goals:
    new_goal, created = NewWellnessGoal.objects.get_or_create(
        id=old_goal.id,  # Intenta mantener el ID si es posible
        defaults={
            'user': old_goal.user,
            'title': old_goal.title,
            'progress': old_goal.progress,
            'color': old_goal.color,
            'icon': old_goal.icon,
            'is_auto_generated': old_goal.is_auto_generated,
            'therapy_related': old_goal.therapy_related,
            'target_progress': old_goal.target_progress
        }
    )
    if not created:
        print(f"Goal con ID {old_goal.id} ya existe en api_wellnessgoal, revisa duplicados.")

# Actualizar referencias en therapy_challenge
challenges = Challenge.objects.all()
for challenge in challenges:
    if challenge.goal_id and not NewWellnessGoal.objects.filter(id=challenge.goal_id).exists():
        print(f"Goal ID {challenge.goal_id} no encontrado, actualizando a None o un valor válido.")
        challenge.goal = None  # O asigna un goal válido si tienes uno por defecto
        challenge.save()
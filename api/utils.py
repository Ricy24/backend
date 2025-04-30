# utils.py
from django.utils import timezone
from datetime import timedelta
from dashboard.models import WellnessGoal
from groq import Groq
from django.conf import settings
import logging

logger = logging.getLogger(__name__)
GROQ_API_KEY = settings.GROQ_API_KEY
GROQ_CLIENT = Groq(api_key=GROQ_API_KEY)

def generate_diagnosis_and_recommendations(responses):
    support_choice = responses.get('support_choice', 'personal')
    
    # Mapear preguntas según el tipo de apoyo
    if support_choice == 'personal':
        anxiety_score = sum([responses.get(q, 0) for q in ['p1', 'p2']])
        depression_score = responses.get('p3', 0)
        goals = {k: responses.get(k, 0) for k in ['pg1', 'pg2', 'pg3']}
    elif support_choice == 'couple':
        anxiety_score = sum([responses.get(q, 0) for q in ['c1', 'c2']])
        depression_score = responses.get('c3', 0)
        goals = {k: responses.get(k, 0) for k in ['cg1', 'cg2', 'cg3']}
    elif support_choice == 'family':
        anxiety_score = sum([responses.get(q, 0) for q in ['f1', 'f2']])
        depression_score = responses.get('f3', 0)
        goals = {k: responses.get(k, 0) for k in ['fg1', 'fg2', 'fg3']}
    else:
        anxiety_score = 0
        depression_score = 0
        goals = {}

    # Derivar el tipo de terapia del support_choice
    therapy_type = {
        'personal': 'individual',
        'couple': 'couple',
        'family': 'family'
    }.get(support_choice, 'individual')

    # Crear prompts personalizados según el tipo de terapia
    if support_choice == 'personal':
        prompt = (
            f"Analiza las respuestas de un usuario que busca apoyo personal:\n"
            f"- Frecuencia de sentirse abrumado por emociones (p1): {responses.get('p1', 0)}/4\n"
            f"- Dificultad para resolver problemas sin ayuda (p2): {responses.get('p2', 0)}/4\n"
            f"- Evitar actividades por ansiedad o tristeza (p3): {responses.get('p3', 0)}/4\n"
            f"- Importancia de manejar estrés (pg1): {goals.get('pg1', 0)}/4\n"
            f"- Importancia de mejorar autoestima (pg2): {goals.get('pg2', 0)}/4\n"
            f"- Importancia de resolver problemas (pg3): {goals.get('pg3', 0)}/4\n"
            f"Devuelve un diagnóstico psicológico detallado, recomendaciones específicas y número estimado de sesiones necesarias en formato:\n"
            f"- Diagnóstico: [texto]\n- Recomendaciones: [texto]\n- Sesiones: [número]"
        )
    elif support_choice == 'couple':
        prompt = (
            f"Analiza las respuestas de un usuario que busca apoyo en pareja:\n"
            f"- Frecuencia de desacuerdos en la relación (c1): {responses.get('c1', 0)}/4\n"
            f"- Insuficiencia en la comunicación con la pareja (c2): {responses.get('c2', 0)}/4\n"
            f"- Desconexión emocional con la pareja (c3): {responses.get('c3', 0)}/4\n"
            f"- Importancia de mejorar comunicación (cg1): {goals.get('cg1', 0)}/4\n"
            f"- Importancia de fortalecer vínculo (cg2): {goals.get('cg2', 0)}/4\n"
            f"- Importancia de gestionar conflictos (cg3): {goals.get('cg3', 0)}/4\n"
            f"Devuelve un diagnóstico detallado sobre la dinámica de pareja, recomendaciones específicas y número estimado de sesiones necesarias en formato:\n"
            f"- Diagnóstico: [texto]\n- Recomendaciones: [texto]\n- Sesiones: [número]"
        )
    elif support_choice == 'family':
        prompt = (
            f"Analiza las respuestas de un usuario que busca apoyo familiar:\n"
            f"- Frecuencia de conflictos significativos en la familia (f1): {responses.get('f1', 0)}/4\n"
            f"- Deficiencia en la comunicación familiar (f2): {responses.get('f2', 0)}/4\n"
            f"- Necesidades emocionales no escuchadas (f3): {responses.get('f3', 0)}/4\n"
            f"- Importancia de mejorar comunicación (fg1): {goals.get('fg1', 0)}/4\n"
            f"- Importancia de resolver conflictos (fg2): {goals.get('fg2', 0)}/4\n"
            f"- Importancia de fortalecer lazos (fg3): {goals.get('fg3', 0)}/4\n"
            f"Devuelve un diagnóstico detallado sobre la dinámica familiar, recomendaciones específicas y número estimado de sesiones necesarias en formato:\n"
            f"- Diagnóstico: [texto]\n- Recomendaciones: [texto]\n- Sesiones: [número]"
        )

    try:
        response = GROQ_CLIENT.chat.completions.create(
            model="mixtral-8x7b-32768",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        result = response.choices[0].message.content.strip()
        
        lines = result.split('\n')
        diagnosis = next((line.replace("Diagnóstico: ", "") for line in lines if "Diagnóstico" in line), "No se detectaron problemas significativos.")
        recommendations = next((line.replace("Recomendaciones: ", "") for line in lines if "Recomendaciones" in line), "Mantener hábitos saludables.")
        sessions_needed = int(next((line.split()[-1] for line in lines if "Sesiones" in line), "2"))

    except Exception as e:
        logger.error(f"Error al consultar Grok: {str(e)}")
        # Lógica de fallback personalizada según el tipo de terapia
        if support_choice == 'personal':
            diagnosis = ""
            recommendations = ""
            sessions_needed = 0
            if anxiety_score > 4:
                diagnosis += "Ansiedad personal moderada a alta detectada."
                recommendations += "Practicar técnicas de mindfulness y ejercicios de respiración diarios."
                sessions_needed += 6
            if depression_score > 2:
                diagnosis += " Posible estado de ánimo bajo relacionado con aislamiento personal."
                recommendations += " Incorporar actividades placenteras y establecer una rutina diaria."
                sessions_needed += 4
            if goals.get('pg1', 0) > 2:
                recommendations += " Aprender estrategias específicas para reducir el estrés."
            if goals.get('pg2', 0) > 2:
                recommendations += " Trabajar en ejercicios de autoafirmación para mejorar la autoestima."
            if goals.get('pg3', 0) > 2:
                recommendations += " Desarrollar habilidades de resolución de problemas estructurada."
            if not diagnosis:
                diagnosis = "No se detectaron problemas significativos en el ámbito personal."
                recommendations = "Continuar con hábitos saludables y autoconocimiento."
                sessions_needed = 2

        elif support_choice == 'couple':
            diagnosis = ""
            recommendations = ""
            sessions_needed = 0
            if anxiety_score > 4:
                diagnosis += "Tensión significativa en la dinámica de pareja detectada."
                recommendations += "Practicar ejercicios de comunicación activa y escucha empática."
                sessions_needed += 8
            if depression_score > 2:
                diagnosis += " Desconexión emocional en la relación."
                recommendations += " Realizar actividades conjuntas para reconectar emocionalmente."
                sessions_needed += 6
            if goals.get('cg1', 0) > 2:
                recommendations += " Implementar sesiones de diálogo estructurado con la pareja."
            if goals.get('cg2', 0) > 2:
                recommendations += " Fomentar momentos de intimidad y apoyo mutuo."
            if goals.get('cg3', 0) > 2:
                recommendations += " Aprender técnicas de resolución de conflictos en pareja."
            if not diagnosis:
                diagnosis = "No se detectaron problemas significativos en la relación de pareja."
                recommendations = "Mantener una comunicación abierta y tiempo de calidad."
                sessions_needed = 3

        elif support_choice == 'family':
            diagnosis = ""
            recommendations = ""
            sessions_needed = 0
            if anxiety_score > 4:
                diagnosis += "Conflictos familiares moderados a altos detectados."
                recommendations += "Establecer reuniones familiares regulares para abordar tensiones."
                sessions_needed += 8
            if depression_score > 2:
                diagnosis += " Falta de soporte emocional en el núcleo familiar."
                recommendations += " Promover actividades familiares que fortalezcan el apoyo mutuo."
                sessions_needed += 6
            if goals.get('fg1', 0) > 2:
                recommendations += " Trabajar en habilidades de comunicación familiar efectiva."
            if goals.get('fg2', 0) > 2:
                recommendations += " Aplicar estrategias de mediación para resolver conflictos."
            if goals.get('fg3', 0) > 2:
                recommendations += " Organizar actividades para fortalecer los lazos familiares."
            if not diagnosis:
                diagnosis = "No se detectaron problemas significativos en la dinámica familiar."
                recommendations = "Fomentar la cohesión y el apoyo dentro de la familia."
                sessions_needed = 3

    return diagnosis, recommendations, sessions_needed, therapy_type
    pass

def generate_wellness_goals_from_assessment(user, responses):

    support_choice = responses.get('support_choice', 'personal')
    
    # Crear prompts personalizados para metas según el tipo de terapia
    if support_choice == 'personal':
        prompt = (
            f"Basado en las respuestas de un usuario que busca apoyo personal, genera 1-3 metas de bienestar:\n"
            f"- Frecuencia de sentirse abrumado por emociones (p1): {responses.get('p1', 0)}/4\n"
            f"- Dificultad para resolver problemas sin ayuda (p2): {responses.get('p2', 0)}/4\n"
            f"- Evitar actividades por ansiedad o tristeza (p3): {responses.get('p3', 0)}/4\n"
            f"- Importancia de manejar estrés (pg1): {responses.get('pg1', 0)}/4\n"
            f"- Importancia de mejorar autoestima (pg2): {responses.get('pg2', 0)}/4\n"
            f"- Importancia de resolver problemas (pg3): {responses.get('pg3', 0)}/4\n"
            f"Devuelve metas en formato: Título: [texto] | Progreso objetivo: [50-100]"
        )
    elif support_choice == 'couple':
        prompt = (
            f"Basado en las respuestas de un usuario que busca apoyo en pareja, genera 1-3 metas de bienestar:\n"
            f"- Frecuencia de desacuerdos en la relación (c1): {responses.get('c1', 0)}/4\n"
            f"- Insuficiencia en la comunicación con la pareja (c2): {responses.get('c2', 0)}/4\n"
            f"- Desconexión emocional con la pareja (c3): {responses.get('c3', 0)}/4\n"
            f"- Importancia de mejorar comunicación (cg1): {responses.get('cg1', 0)}/4\n"
            f"- Importancia de fortalecer vínculo (cg2): {responses.get('cg2', 0)}/4\n"
            f"- Importancia de gestionar conflictos (cg3): {responses.get('cg3', 0)}/4\n"
            f"Devuelve metas en formato: Título: [texto] | Progreso objetivo: [50-100]"
        )
    elif support_choice == 'family':
        prompt = (
            f"Basado en las respuestas de un usuario que busca apoyo familiar, genera 1-3 metas de bienestar:\n"
            f"- Frecuencia de conflictos significativos en la familia (f1): {responses.get('f1', 0)}/4\n"
            f"- Deficiencia en la comunicación familiar (f2): {responses.get('f2', 0)}/4\n"
            f"- Necesidades emocionales no escuchadas (f3): {responses.get('f3', 0)}/ radially4\n"
            f"- Importancia de mejorar comunicación (fg1): {responses.get('fg1', 0)}/4\n"
            f"- Importancia de resolver conflictos (fg2): {responses.get('fg2', 0)}/4\n"
            f"- Importancia de fortalecer lazos (fg3): {responses.get('fg3', 0)}/4\n"
            f"Devuelve metas en formato: Título: [texto] | Progreso objetivo: [50-100]"
        )

    try:
        response = GROQ_CLIENT.chat.completions.create(
            model="mixtral-8x7b-32768",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300
        )
        result = response.choices[0].message.content.strip()
        
        goals = []
        for line in result.split('\n'):
            if line.strip():
                parts = line.split('|')
                if len(parts) >= 2:
                    title = parts[0].replace("Título: ", "").strip()
                    target_progress = int(parts[1].replace("Progreso objetivo: ", "").strip())
                    goals.append({
                        'title': title,
                        'progress': 0,
                        'color': 'from-blue-500-to-cyan-600' if support_choice == 'personal' else 
                                 'from-purple-500-to-indigo-600' if support_choice == 'couple' else 
                                 'from-green-500-to-lime-600',
                        'icon': 'Target',
                        'is_auto_generated': True,
                        'therapy_related': True,
                        'target_progress': target_progress
                    })
        
        if not goals:
            raise ValueError("No se generaron metas válidas")
        
    except Exception as e:
        logger.error(f"Error al generar metas con Grok: {str(e)}")
        goals = []
        if support_choice == 'personal':
            if responses.get('p1', 0) > 2 or responses.get('p2', 0) > 2:
                goals.append({
                    'title': 'Reducir mi ansiedad personal',
                    'progress': 0,
                    'color': 'from-blue-500-to-cyan-600',
                    'icon': 'Target',
                    'is_auto_generated': True,
                    'therapy_related': True,
                    'target_progress': 80
                })
            if responses.get('pg2', 0) > 2:
                goals.append({
                    'title': 'Fortalecer mi autoestima',
                    'progress': 0,
                    'color': 'from-blue-500-to-cyan-600',
                    'icon': 'Target',
                    'is_auto_generated': True,
                    'therapy_related': True,
                    'target_progress': 75
                })
        elif support_choice == 'couple':
            if responses.get('c1', 0) > 2 or responses.get('c2', 0) > 2:
                goals.append({
                    'title': 'Mejorar la comunicación en pareja',
                    'progress': 0,
                    'color': 'from-purple-500-to-indigo-600',
                    'icon': 'Target',
                    'is_auto_generated': True,
                    'therapy_related': True,
                    'target_progress': 75
                })
            if responses.get('cg2', 0) > 2:
                goals.append({
                    'title': 'Fortalecer el vínculo emocional con mi pareja',
                    'progress': 0,
                    'color': 'from-purple-500-to-indigo-600',
                    'icon': 'Target',
                    'is_auto_generated': True,
                    'therapy_related': True,
                    'target_progress': 70
                })
        elif support_choice == 'family':
            if responses.get('f1', 0) > 2 or responses.get('f2', 0) > 2:
                goals.append({
                    'title': 'Reducir conflictos familiares',
                    'progress': 0,
                    'color': 'from-green-500-to-lime-600',
                    'icon': 'Target',
                    'is_auto_generated': True,
                    'therapy_related': True,
                    'target_progress': 70
                })
            if responses.get('fg3', 0) > 2:
                goals.append({
                    'title': 'Fortalecer los lazos familiares',
                    'progress': 0,
                    'color': 'from-green-500-to-lime-600',
                    'icon': 'Target',
                    'is_auto_generated': True,
                    'therapy_related': True,
                    'target_progress': 75
                })
        if not goals:
            goals.append({
                'title': f'Mantener mi bienestar {"personal" if support_choice == "personal" else "en pareja" if support_choice == "couple" else "familiar"}',
                'progress': 0,
                'color': 'from-green-500-to-lime-600',
                'icon': 'Target',
                'is_auto_generated': True,
                'therapy_related': False,
                'target_progress': 50
            })
    
    for goal_data in goals:
        WellnessGoal.objects.get_or_create(
            user=user,
            title=goal_data['title'],
            defaults=goal_data
        )
    return goals
    pass
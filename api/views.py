# api/views.py
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate, login, logout
from django.utils import timezone
import requests
import logging
from django.db.models import Count
import uuid
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .models import Terapia, MiembroTerapia, InvitacionTerapia, Usuario, InitialAssessment, WellnessGoal, Resource
from .serializers import TerapiaSerializer, MiembroTerapiaSerializer, RegisterSerializer, UserSerializer, PsychologistRegisterSerializer 
from psychologist.models import Availability, PsychologistProfile  # Seguimos necesitando esto para ScheduleFreeSessionView
from google_calendar.models import CalendarEvent
from groq import Groq
from datetime import datetime
from dashboard.views import calculate_wellness_days
from dashboard.models import Mood
from community.views import Post 
from community.models import Post 
from emails.utils import send_brevo_email
from chat.models import ChatConfig
from rest_framework.parsers import MultiPartParser, FormParser # Añadir parsers explícitamente
 


User = get_user_model()
logger = logging.getLogger(__name__)

# Configuración de claves API desde settings.py
GROQ_API_KEY = settings.GROQ_API_KEY
GROQ_CLIENT = Groq(api_key=GROQ_API_KEY)

# Función auxiliar para generar diagnóstico y recomendaciones

def generate_diagnosis_and_recommendations(responses):
    """
    Genera un diagnóstico, recomendaciones y métricas basadas en las respuestas
    de la evaluación inicial.
    """
    support_choice = responses.get('support_choice', 'personal')
    therapy_type = {'personal': 'individual', 'couple': 'couple', 'family': 'family'}.get(support_choice, 'individual')

    # --- Inicialización de variables ---
    diagnostic_keys, goal_keys, labels = [], [], {}
    diagnosis = "No se pudo generar un diagnóstico inicial." # Valor por defecto
    recommendations = []
    sessions_needed = 0
    severity = 'unknown'
    metrics = {}
    goals = {}

    # --- Definir claves y etiquetas según tipo de apoyo ---
    if support_choice == 'personal':
        diagnostic_keys = ['p1', 'p2', 'p3']
        goal_keys = ['pg1', 'pg2', 'pg3']
        labels = {
            'p1': 'Emociones abrumadoras', 'p2': 'Dificultad para resolver problemas',
            'p3': 'Evitación de actividades por falta de motivación'
        }
    elif support_choice == 'couple':
        diagnostic_keys = ['c1', 'c2', 'c3']
        goal_keys = ['cg1', 'cg2', 'cg3']
        labels = {
            'c1': 'Frecuencia de desacuerdos', 'c2': 'Insuficiencia en comunicación',
            'c3': 'Desconexión emocional'
        }
    elif support_choice == 'family':
        diagnostic_keys = ['f1', 'f2', 'f3']
        goal_keys = ['fg1', 'fg2', 'fg3']
        labels = {
            'f1': 'Conflictos significativos', 'f2': 'Deficiencia en comunicación',
            'f3': 'Necesidades emocionales no atendidas'
        }
    else:
        # Caso: support_choice inválido o no proporcionado
        logger.warning(f"Support choice inválido o no reconocido: {support_choice}. Usando valores por defecto.")
        diagnosis = "Tipo de apoyo no reconocido. No se puede generar diagnóstico detallado."
        # Las variables ya están inicializadas con valores por defecto

    # --- Calcular puntuaciones y métricas (solo si hay claves) ---
    diagnostic_score = 0
    if diagnostic_keys:
        try:
            diagnostic_score = sum(int(responses.get(key, 0)) for key in diagnostic_keys)
            goals = {key: int(responses.get(key, 0)) for key in goal_keys}
            metrics = {
                key: {
                    'label': labels.get(key, key),
                    'score': int(responses.get(key, 0) * 25), # Normalizado a 100 y asegurar entero
                    'description': f"{labels.get(key, key)}: {int(responses.get(key, 0))}/4"
                } for key in diagnostic_keys if key in responses # Asegurar que la clave existe en responses
            }

            # Determinar nivel de severidad
            if diagnostic_score <= 3: severity = 'low'
            elif 4 <= diagnostic_score <= 7: severity = 'moderate'
            elif 8 <= diagnostic_score <= 10: severity = 'high'
            else: severity = 'very_high' # diagnostic_score > 10

        except (TypeError, ValueError) as e:
            logger.error(f"Error al calcular scores/métricas. Responses: {responses}. Error: {e}")
            severity = 'error'
            diagnosis = "Error al procesar las respuestas numéricas."
            metrics = {} # Resetear métricas en caso de error
            goals = {}   # Resetear goals en caso de error
    else:
        logger.info("No se definieron claves diagnósticas, no se calcularán scores ni métricas.")


    # --- Generar diagnóstico y recomendaciones detallados (si no hubo error y hay métricas) ---
    if severity != 'error' and metrics:
        if support_choice == 'personal':
            if severity == 'low':
                diagnosis = f"""Tu bienestar emocional parece estar en un estado generalmente estable. Las dificultades que enfrentas, como sentirte abrumado por tus emociones ({metrics.get('p1', {}).get('score', 'N/A')}%), tener problemas para resolver situaciones sin apoyo ({metrics.get('p2', {}).get('score', 'N/A')}%) o evitar actividades por falta de motivación ({metrics.get('p3', {}).get('score', 'N/A')}%), son mínimas y no parecen interferir significativamente en tu vida diaria. Esto sugiere una buena capacidad de afrontamiento, aunque hay áreas que podrías fortalecer para prevenir futuros desafíos."""
                recommendations = [
                    "Lleva un diario emocional para identificar patrones en tus estados de ánimo (5-10 min diarios).",
                    "Practica técnicas de respiración diafragmática para mantener la calma en momentos de estrés.",
                    "Establece metas pequeñas y alcanzables para aumentar tu sentido de logro y motivación."
                ]
                sessions_needed = 2
            elif severity == 'moderate':
                diagnosis = f"""Presentas un nivel moderado de desafíos en tu bienestar personal. Las emociones abrumadoras alcanzan un {metrics.get('p1', {}).get('score', 'N/A')}%, lo que indica que en ocasiones te sientes superado por lo que sientes. La dificultad para resolver problemas sin ayuda ({metrics.get('p2', {}).get('score', 'N/A')}%) sugiere una posible dependencia de apoyo externo, y la evitación de actividades por falta de motivación ({metrics.get('p3', {}).get('score', 'N/A')}%) podría estar afectando tu productividad o satisfacción personal. Esto podría reflejar estrés acumulado o una autoestima ligeramente comprometida, pero con intervención adecuada, puedes recuperar el equilibrio."""
                recommendations = [
                    "Inicia con técnicas de manejo del estrés, como la relajación progresiva de Jacobson (15 min diarios).",
                    "Dedica tiempo semanal a una actividad placentera que refuerce tu motivación (ej., paseos, hobbies).",
                    "Practica afirmaciones positivas diarias para fortalecer tu autoestima.",
                    "Considera una consulta psicológica para explorar las causas de estas dificultades."
                ]
                sessions_needed = 6
            elif severity == 'high':
                diagnosis = f"""Estás enfrentando desafíos significativos en tu bienestar personal. Con un nivel de emociones abrumadoras de {metrics.get('p1', {}).get('score', 'N/A')}%, es probable que sientas ansiedad o desbordamiento emocional con frecuencia. La dificultad para resolver problemas sin ayuda ({metrics.get('p2', {}).get('score', 'N/A')}%) podría indicar una baja confianza en tus habilidades de afrontamiento, y la evitación de actividades ({metrics.get('p3', {}).get('score', 'N/A')}%) sugiere un impacto notable en tu vida diaria, posiblemente relacionado con síntomas depresivos o agotamiento. Este patrón merece atención profesional para evitar que se agrave."""
                recommendations = [
                    "Implementa un plan estructurado de manejo emocional, como la técnica de 'tiempo fuera' (20-30 min diarios).",
                    "Busca apoyo psicológico urgente para trabajar en estrategias de afrontamiento.",
                    "Incorpora actividades placenteras en una rutina diaria para contrarrestar la evitación.",
                    "Apóyate en amigos o familia como red de soporte inicial."
                ]
                sessions_needed = 10
            elif severity == 'very_high':
                diagnosis = f"""Tu bienestar personal está en un estado crítico. Las emociones abrumadoras alcanzan un {metrics.get('p1', {}).get('score', 'N/A')}%, lo que sugiere una posible presencia de ansiedad generalizada o estrés severo. La dificultad extrema para resolver problemas sin ayuda ({metrics.get('p2', {}).get('score', 'N/A')}%) podría reflejar una percepción de impotencia, y la alta evitación de actividades ({metrics.get('p3', {}).get('score', 'N/A')}%) apunta a un retraimiento significativo, potencialmente vinculado a depresión o burnout. Es crucial actuar de inmediato para proteger tu salud mental."""
                recommendations = [
                    "Consulta a un psicólogo o psiquiatra lo antes posible para una evaluación completa.",
                    "Prueba la técnica de grounding (5-4-3-2-1) para reducir la intensidad emocional en crisis.",
                    "Establece una rutina mínima con apoyo externo para recuperar funcionalidad.",
                    "Considera informar a un ser querido para que te acompañe en este proceso."
                ]
                sessions_needed = 14

            # Recomendaciones por metas (con verificación de existencia de claves)
            if goal_keys and len(goal_keys) > 0 and goals.get(goal_keys[0], 0) > 2: recommendations.append("Aprende la técnica de 'parada de pensamiento' para interrumpir patrones de estrés.")
            if goal_keys and len(goal_keys) > 1 and goals.get(goal_keys[1], 0) > 2: recommendations.append("Realiza ejercicios de gratitud diarios (anota 3 cosas positivas cada día).")
            if goal_keys and len(goal_keys) > 2 and goals.get(goal_keys[2], 0) > 2: recommendations.append("Practica el modelo de resolución de problemas estructurado: define, analiza, actúa.")

        elif support_choice == 'couple':
            if severity == 'low':
                diagnosis = f"""Tu relación de pareja parece estable, con desafíos menores. Los desacuerdos ocurren con una frecuencia de {metrics.get('c1', {}).get('score', 'N/A')}%, lo que es normal en cualquier dinámica interpersonal. La comunicación, con un {metrics.get('c2', {}).get('score', 'N/A')}%, es adecuada en general, y la desconexión emocional ({metrics.get('c3', {}).get('score', 'N/A')}%) no parece ser un problema significativo. Esto indica una base sólida, pero hay espacio para mejorar la conexión y prevenir tensiones futuras."""
                recommendations = [
                    "Dedica 10-15 minutos diarios a conversar con tu pareja sobre temas cotidianos o emociones.",
                    "Planifica una actividad semanal juntos (ej., cena, paseo) para fortalecer el vínculo.",
                    "Practica escucha activa: repite lo que tu pareja dice para confirmar comprensión."
                ]
                sessions_needed = 3
            elif severity == 'moderate':
                diagnosis = f"""Tu relación enfrenta dificultades moderadas. Los desacuerdos frecuentes ({metrics.get('c1', {}).get('score', 'N/A')}%) sugieren tensiones recurrentes que podrían derivar de malentendidos o expectativas no alineadas. La comunicación insuficiente ({metrics.get('c2', {}).get('score', 'N/A')}%) indica barreras en la expresión o comprensión mutua, y la desconexión emocional ({metrics.get('c3', {}).get('score', 'N/A')}%) podría estar erosionando la intimidad. Aunque manejable, este patrón requiere atención para evitar un deterioro mayor."""
                recommendations = [
                    "Establece un 'momento de pareja' semanal para discutir temas importantes sin interrupciones.",
                    "Practica la técnica de 'hablar en primera persona' (ej., 'me siento...' en lugar de 'tú haces...').",
                    "Planifica actividades recreativas conjuntas para reconectar emocionalmente.",
                    "Considera terapia de pareja si las tensiones persisten."
                ]
                sessions_needed = 8
            elif severity == 'high':
                diagnosis = f"""Tu relación presenta problemas significativos. La alta frecuencia de desacuerdos ({metrics.get('c1', {}).get('score', 'N/A')}%) apunta a conflictos recurrentes que podrían estar afectando la estabilidad emocional de ambos. La comunicación insuficiente ({metrics.get('c2', {}).get('score', 'N/A')}%) sugiere una ruptura en el diálogo, y la desconexión emocional marcada ({metrics.get('c3', {}).get('score', 'N/A')}%) podría indicar una crisis relacional. Es probable que haya resentimientos acumulados o necesidades no satisfechas que requieren intervención urgente."""
                recommendations = [
                    "Inicia diálogos estructurados (20-30 min) con reglas claras: sin interrupciones, solo escucha.",
                    "Busca apoyo profesional urgente para mediar y reparar la dinámica.",
                    "Escribe cartas positivas a tu pareja para reconectar desde un lugar seguro.",
                    "Establece límites claros para reducir conflictos mientras trabajas en la relación."
                ]
                sessions_needed = 12
            elif severity == 'very_high':
                diagnosis = f"""Tu relación está en una crisis severa. Los desacuerdos constantes ({metrics.get('c1', {}).get('score', 'N/A')}%) reflejan un nivel crítico de conflicto, posiblemente con enfrentamientos frecuentes. La comunicación casi inexistente ({metrics.get('c2', {}).get('score', 'N/A')}%) indica un colapso en el intercambio emocional, y la desconexión extrema ({metrics.get('c3', {}).get('score', 'N/A')}%) sugiere una alienación profunda. Este estado podría derivar en una ruptura si no se interviene de inmediato."""
                recommendations = [
                    "Consulta a un terapeuta de pareja urgentemente para evaluar la viabilidad de la relación.",
                    "Establece un 'alto al fuego' temporal: evita discusiones hasta la primera sesión.",
                    "Prueba ejercicios de reconexión básicos (ej., recordar momentos felices juntos).",
                    "Evalúa individualmente tus necesidades y expectativas para clarificar el camino."
                ]
                sessions_needed = 16

            # Recomendaciones por metas
            if goal_keys and len(goal_keys) > 0 and goals.get(goal_keys[0], 0) > 2: recommendations.append("Participa en un taller de comunicación asertiva con tu pareja.")
            if goal_keys and len(goal_keys) > 1 and goals.get(goal_keys[1], 0) > 2: recommendations.append("Dedica tiempo a actividades íntimas que refuercen el apego (ej., contacto físico).")
            if goal_keys and len(goal_keys) > 2 and goals.get(goal_keys[2], 0) > 2: recommendations.append("Aprende la técnica de 'pausa activa': detén una discusión y retoma tras 10 min.")

        elif support_choice == 'family':
            if severity == 'low':
                diagnosis = f"""La dinámica familiar es mayormente saludable, con conflictos mínimos ({metrics.get('f1', {}).get('score', 'N/A')}%). La comunicación, aunque no perfecta ({metrics.get('f2', {}).get('score', 'N/A')}%), parece funcional, y las necesidades emocionales no atendidas ({metrics.get('f3', {}).get('score', 'N/A')}%) no son un problema grave. Esto refleja una familia con buena cohesión, pero con oportunidades para fortalecer los lazos y prevenir futuros roces."""
                recommendations = [
                    "Organiza una actividad familiar semanal (ej., juego de mesa, comida juntos).",
                    "Fomenta reuniones breves (10 min) para que todos compartan cómo se sienten.",
                    "Celebra logros familiares para reforzar la unión."
                ]
                sessions_needed = 3
            elif severity == 'moderate':
                diagnosis = f"""Tu familia enfrenta dificultades moderadas. Los conflictos significativos ({metrics.get('f1', {}).get('score', 'N/A')}%) indican tensiones ocasionales que podrían surgir de roles poco claros o estrés externo. La comunicación deficiente ({metrics.get('f2', {}).get('score', 'N/A')}%) sugiere que no todos se sienten escuchados, y las necesidades emocionales no atendidas ({metrics.get('f3', {}).get('score', 'N/A')}%) podrían generar frustración. Aunque funcional, la dinámica necesita ajustes para mejorar la armonía."""
                recommendations = [
                    "Realiza reuniones familiares semanales (15-20 min) con un turno para cada miembro.",
                    "Practica escucha activa: parafrasea lo que otros dicen para validar sus emociones.",
                    "Planifica actividades conjuntas para reducir tensiones y fomentar colaboración.",
                    "Considera apoyo profesional si los conflictos escalan."
                ]
                sessions_needed = 8
            elif severity == 'high':
                diagnosis = f"""La dinámica familiar presenta problemas significativos. Los conflictos frecuentes ({metrics.get('f1', {}).get('score', 'N/A')}%) sugieren una falta de resolución efectiva, posiblemente alimentada por malentendidos o dinámicas de poder desbalanceadas. La comunicación muy deficiente ({metrics.get('f2', {}).get('score', 'N/A')}%) indica una barrera en el diálogo, y las necesidades emocionales no atendidas ({metrics.get('f3', {}).get('score', 'N/A')}%) podrían estar generando resentimiento o aislamiento. Es necesario intervenir para restaurar el equilibrio."""
                recommendations = [
                    "Inicia reuniones familiares con un moderador (familiar neutral o profesional) si es posible.",
                    "Busca terapia familiar urgente para abordar las tensiones subyacentes.",
                    "Establece reglas claras de comunicación (ej., sin interrupciones, turnos para hablar).",
                    "Promueve actividades de vínculo (ej., proyectos conjuntos) para reconstruir la confianza."
                ]
                sessions_needed = 12
            elif severity == 'very_high':
                diagnosis = f"""La dinámica familiar está en un estado crítico. Los conflictos severos ({metrics.get('f1', {}).get('score', 'N/A')}%) reflejan una ruptura en la cohesión, posiblemente con enfrentamientos frecuentes o roles disfuncionales. La comunicación casi nula ({metrics.get('f2', {}).get('score', 'N/A')}%) apunta a un colapso en la interacción, y las necesidades emocionales gravemente desatendidas ({metrics.get('f3', {}).get('score', 'N/A')}%) sugieren aislamiento o rechazo entre miembros. Este nivel requiere intervención inmediata para evitar daños duraderos."""
                recommendations = [
                    "Consulta a un terapeuta familiar urgentemente para mediar y reestructurar la dinámica.",
                    "Establece un espacio seguro temporal (ej., acuerdos básicos de respeto).",
                    "Prueba actividades guiadas de reconexión (ej., cartas de aprecio entre miembros).",
                    "Evalúa individualmente el impacto emocional para cada miembro."
                ]
                sessions_needed = 16

            # Recomendaciones por metas
            if goal_keys and len(goal_keys) > 0 and goals.get(goal_keys[0], 0) > 2: recommendations.append("Implementa un sistema de comunicación como un 'buzón anónimo' para expresar inquietudes.")
            if goal_keys and len(goal_keys) > 1 and goals.get(goal_keys[1], 0) > 2: recommendations.append("Practica técnicas de mediación familiar (ej., resolución en 3 pasos).")
            if goal_keys and len(goal_keys) > 2 and goals.get(goal_keys[2], 0) > 2: recommendations.append("Organiza eventos regulares (ej., cenas mensuales) para fortalecer la unión.")

    # Asegurar que diagnosis tiene un valor si no se asignó antes
    if 'diagnosis' not in locals() or not diagnosis:
         diagnosis = "No se pudo generar un diagnóstico detallado con los datos proporcionados."
         logger.warning(f"Diagnóstico no generado para {support_choice} con severidad {severity}")


    # --- Retornar resultados ---
    return {
        'diagnosis': diagnosis.strip(), # Limpiar espacios extra
        'metrics': metrics, # Retornar el diccionario de métricas
        'recommendations': recommendations,
        'sessions_needed': sessions_needed,
        'therapy_type': therapy_type,
        'severity': severity
    }
# Función auxiliar para generar metas de bienestar sin API externa
def generate_wellness_goals_from_assessment(user, responses):
    support_choice = responses.get('support_choice', 'personal')
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
        if responses.get('pg3', 0) > 2:
            goals.append({
                'title': 'Mejorar mis habilidades de resolución de problemas',
                'progress': 0,
                'color': 'from-blue-500-to-cyan-600',
                'icon': 'Target',
                'is_auto_generated': True,
                'therapy_related': True,
                'target_progress': 70
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
        if responses.get('cg3', 0) > 2:
            goals.append({
                'title': 'Gestionar mejor los conflictos en pareja',
                'progress': 0,
                'color': 'from-purple-500-to-indigo-600',
                'icon': 'Target',
                'is_auto_generated': True,
                'therapy_related': True,
                'target_progress': 65
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
        if responses.get('fg1', 0) > 2:
            goals.append({
                'title': 'Mejorar la comunicación familiar',
                'progress': 0,
                'color': 'from-green-500-to-lime-600',
                'icon': 'Target',
                'is_auto_generated': True,
                'therapy_related': True,
                'target_progress': 70
            })

    # Meta por defecto si no hay otras
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

    # Guardar metas en la base de datos
    for goal_data in goals:
        WellnessGoal.objects.get_or_create(
            user=user,
            title=goal_data['title'],
            defaults=goal_data
        )
    return goals

# Vista para enviar la evaluación inicial
class SubmitInitialAssessmentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        try:
            responses = request.data.get('responses', {})
            logger.info(f"--- [Assessment START] para {user.email} ---")
            logger.info(f"[Assessment] Datos recibidos: {responses}")

            if not isinstance(responses, dict) or not responses or 'support_choice' not in responses:
                logger.error(f"[Assessment] Validación fallida. Responses: {responses}")
                return Response({'error': 'Responses son requeridas, incluyendo support_choice'}, status=status.HTTP_400_BAD_REQUEST)

            # Generar resultados individuales
            result = generate_diagnosis_and_recommendations(responses)
            diagnosis = result.get('diagnosis', '').strip()
            metrics_dict = result.get('metrics', {})
            recommendations = result.get('recommendations', [])
            sessions_needed = result.get('sessions_needed', 0)
            therapy_type = result.get('therapy_type', 'individual')
            severity = result.get('severity', 'unknown')

            logger.info(f"[Assessment] Diagnóstico individual generado: '{diagnosis}' (Tipo: {therapy_type})")
            if not diagnosis:
                logger.warning(f"[Assessment] ¡El diagnóstico individual generado está VACÍO!")

            metrics_list = [
                {'label': metric.get('label', key), 'score': metric.get('score', 0)}
                for key, metric in metrics_dict.items()
            ] if isinstance(metrics_dict, dict) else []

            # Guardar/Actualizar la evaluación individual del usuario
            assessment, assessment_created = InitialAssessment.objects.update_or_create(
                user=user,
                defaults={
                    'responses': responses,
                    'diagnosis': diagnosis,
                    'therapy_recommendations': '\n'.join(recommendations),
                    'sessions_needed': sessions_needed,
                    'therapy_type': therapy_type,  # Ahora será 'couple', 'family', o 'individual'
                    'completed': True
                }
            )
            logger.info(f"[Assessment] Evaluación inicial {'creada' if assessment_created else 'actualizada'} para {user.email} (ID: {assessment.id}). Completada: {assessment.completed}")

            generated_goals = generate_wellness_goals_from_assessment(user, responses)

            if user.is_new_user:
                user.is_new_user = False
                user.save()
                logger.info(f"[User] {user.email} marcado como is_new_user=False.")

            # --- Parte 2: Generar diagnóstico combinado SI APLICA ---
            terapia_para_combinado = None
            combined_diagnosis_processed = False
            # Mapear therapy_type a los valores de Terapia
            therapy_type_map = {'individual': 'individual', 'couple': 'pareja', 'family': 'familiar'}
            mapped_therapy_type = therapy_type_map.get(therapy_type, therapy_type)

            if mapped_therapy_type in ['pareja', 'familiar']:
                logger.info(f"[Combined Diag Check] Iniciando chequeo para {user.email} (terapia tipo {mapped_therapy_type})...")
                miembro_relacion = MiembroTerapia.objects.filter(
                    usuario=user,
                    terapia__tipo=mapped_therapy_type
                ).select_related('terapia').first()

                if miembro_relacion:
                    combined_diagnosis_processed = True
                    terapia_para_combinado = miembro_relacion.terapia
                    logger.info(f"[Combined Diag Check] Usuario pertenece a Terapia ID: {terapia_para_combinado.id}. Verificando estado...")

                    terapia_para_combinado.refresh_from_db()

                    if terapia_para_combinado.combined_diagnosis:
                        logger.info(f"[Combined Diag Check] Diagnóstico ya existe en DB para Terapia {terapia_para_combinado.id}: '{terapia_para_combinado.combined_diagnosis[:100]}...'")
                    else:
                        MINIMUM_MEMBERS_FOR_COMBINED = 2
                        miembros_query = MiembroTerapia.objects.filter(terapia=terapia_para_combinado)
                        miembro_user_ids = list(miembros_query.values_list('usuario_id', flat=True))

                        completed_assessments = InitialAssessment.objects.filter(
                            user_id__in=miembro_user_ids,
                            completed=True
                        )
                        completed_assessments_count = completed_assessments.count()

                        expected_members = terapia_para_combinado.limite_miembros
                        logger.info(f"[Combined Diag Check] Terapia {terapia_para_combinado.id}: {completed_assessments_count} evaluaciones completas encontradas para miembros {miembro_user_ids}. (Mínimo req: {MINIMUM_MEMBERS_FOR_COMBINED}, Límite máx: {expected_members}).")

                        if completed_assessments_count >= MINIMUM_MEMBERS_FOR_COMBINED:
                            logger.info(f"[Combined Diag Logic] ¡Condiciones cumplidas! ({completed_assessments_count} >= {MINIMUM_MEMBERS_FOR_COMBINED}). Generando diagnóstico combinado...")

                            diagnosticos_individuales = []
                            valid_diagnoses_found = 0
                            assessments_completos_list = list(completed_assessments.select_related('user'))

                            for assessment_miembro in assessments_completos_list:
                                diag_text = assessment_miembro.diagnosis
                                if diag_text and diag_text.strip():
                                    diagnosticos_individuales.append(f"Diagnóstico de {assessment_miembro.user.email}: {diag_text.strip()}")
                                    valid_diagnoses_found += 1
                                    logger.info(f"[Combined Diag Logic] Diagnóstico VÁLIDO encontrado para {assessment_miembro.user.email}.")
                                else:
                                    logger.warning(f"[Combined Diag Logic] Diagnóstico INVÁLIDO (vacío o nulo) para {assessment_miembro.user.email}.")

                            logger.info(f"[Combined Diag Logic] Recopilados {valid_diagnoses_found} diagnósticos individuales válidos.")

                            if valid_diagnoses_found >= MINIMUM_MEMBERS_FOR_COMBINED:
                                prompt = (
                                    "Eres un psicólogo experto en terapia de pareja y familiar. Basándote en los siguientes diagnósticos individuales, genera un diagnóstico combinado claro, conciso y profesional que resuma los problemas comunes y las dinámicas relacionales entre los miembros. Omite detalles específicos de cada persona y enfócate en patrones generales. Proporciona el resultado en español.\n\n"
                                    + "\n".join(diagnosticos_individuales) +
                                    "\n\nResumen Combinado:"
                                )
                                logger.info(f"[Combined Diag Groq] Enviando prompt a Groq (Terapia {terapia_para_combinado.id}, {len(diagnosticos_individuales)} diags)...")

                                try:
                                    response = GROQ_CLIENT.chat.completions.create(
                                        model="llama-3.1-8b-instant",
                                        messages=[
                                            {"role": "system", "content": "Eres un psicólogo experto en terapia relacional."},
                                            {"role": "user", "content": prompt}
                                        ],
                                        max_tokens=1200,
                                        temperature=0.7
                                    )

                                    combined_diagnosis_text = response.choices[0].message.content.strip()
                                    logger.info(f"[Combined Diag Groq] Respuesta recibida de Groq: '{combined_diagnosis_text[:100]}...'")

                                    if combined_diagnosis_text:
                                        terapia_para_combinado.combined_diagnosis = combined_diagnosis_text
                                        terapia_para_combinado.save()
                                        terapia_para_combinado.refresh_from_db()
                                        if terapia_para_combinado.combined_diagnosis == combined_diagnosis_text:
                                            logger.info(f"[Combined Diag Save] ¡ÉXITO! Diagnóstico combinado guardado para Terapia {terapia_para_combinado.id}.")
                                        else:
                                            logger.error(f"[Combined Diag Save] ¡FALLO! El diagnóstico no se guardó correctamente en DB.")
                                    else:
                                        logger.error(f"[Combined Diag Groq] Groq devolvió un diagnóstico vacío.")
                                except Exception as groq_error:
                                    logger.error(f"[Combined Diag Groq] ERROR al llamar a Groq: {str(groq_error)}", exc_info=True)
                            else:
                                logger.warning(f"[Combined Diag Logic] No hay suficientes diagnósticos válidos ({valid_diagnoses_found} < {MINIMUM_MEMBERS_FOR_COMBINED}).")
                        else:
                            logger.info(f"[Combined Diag Check] Aún no hay suficientes evaluaciones completadas ({completed_assessments_count} < {MINIMUM_MEMBERS_FOR_COMBINED}).")

            # --- Parte 3: Devolver respuesta ---
            logger.info(f"--- [Assessment END] para {user.email} ---")
            return Response({
                'diagnosis': diagnosis,
                'metrics': metrics_list,
                'recommendations': recommendations,
                'sessionsNeeded': sessions_needed,
                'therapyType': therapy_type,
                'severity': severity,
                'generatedGoals': [
                    {'title': g['title'], 'progress': g['progress'], 'color': g['color'], 'icon': g['icon'], 'target_progress': g['target_progress']}
                    for g in generated_goals
                ],
                'support_choice': responses.get('support_choice', 'personal'),
                'combined_diagnosis': terapia_para_combinado.combined_diagnosis if terapia_para_combinado else None
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[Assessment] ERROR CRÍTICO: {str(e)}", exc_info=True)
            return Response({'error': f'Error procesando la evaluación: {str(e)}', 'metrics': []}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# ... (resto del código sin cambios)
    
class CombinedDiagnosisView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            user_assessment = InitialAssessment.objects.filter(user=user).first()
            if not user_assessment:
                return Response({'error': 'No se encontró una evaluación inicial para el usuario.'}, status=status.HTTP_400_BAD_REQUEST)

            therapy_type = user_assessment.therapy_type
            miembro = MiembroTerapia.objects.filter(usuario=user).first()
            if not miembro:
                return Response({'error': 'Usuario no está vinculado a ninguna terapia.'}, status=status.HTTP_400_BAD_REQUEST)

            terapia = miembro.terapia
            combined_diagnosis = terapia.combined_diagnosis if therapy_type in ['pareja', 'familiar'] else user_assessment.diagnosis

            return Response({
                'combined_diagnosis': combined_diagnosis or user_assessment.diagnosis,
                'therapy_type': therapy_type
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error en CombinedDiagnosisView: {str(e)}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
# Vista para crear un nuevo recurso (solo psicólogos o admin)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_resource(request):
    try:
        user = request.user
        if not user.is_psychologist and not user.is_staff:
            return Response({'error': 'Solo psicólogos o administradores pueden crear recursos'}, status=status.HTTP_403_FORBIDDEN)
        
        title = request.data.get('title')
        resource_type = request.data.get('type')
        content = request.data.get('content')
        diagnosis = request.data.get('diagnosis', None)  # Opcional
        
        if not title or not resource_type or not content:
            return Response({'error': 'Título, tipo y contenido son obligatorios'}, status=status.HTTP_400_BAD_REQUEST)
        
        if resource_type not in [choice[0] for choice in Resource.RESOURCE_TYPES]:
            return Response({'error': 'Tipo de recurso inválido'}, status=status.HTTP_400_BAD_REQUEST)
        
        resource = Resource.objects.create(
            title=title,
            type=resource_type,
            content=content,
            diagnosis=diagnosis
        )
        
        return Response({
            'resource': {
                'id': resource.id,
                'title': resource.title,
                'type': resource.type,
                'content': resource.content,
                'diagnosis': resource.diagnosis
            }
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.error(f"Error en create_resource: {str(e)}", exc_info=True)
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Vista para obtener recursos personalizados según el diagnóstico del usuario
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_personalized_resources(request):
    try:
        user = request.user
        assessment = InitialAssessment.objects.filter(user=user).first()
        
        if not assessment or not assessment.completed or not assessment.diagnosis:
            return Response({'resources': []}, status=status.HTTP_200_OK)
        
        # Extraer palabras clave del diagnóstico
        diagnosis_keywords = assessment.diagnosis.lower().split()
        relevant_diagnoses = [
            'ansiedad', 'depresión', 'estrés', 'insomnio', 'bipolar', 'toc', 
            'conflicto', 'comunicación', 'vínculo', 'emocional', 'pareja', 'familiar'
        ]
        
        # Filtrar recursos que coincidan con el diagnóstico o sean genéricos
        resources = Resource.objects.filter(
            Q(diagnosis__isnull=True) |  # Recursos genéricos
            Q(diagnosis__in=[kw for kw in diagnosis_keywords if kw in relevant_diagnoses])
        )
        
        data = [
            {
                'id': r.id,
                'title': r.title,
                'type': r.type,
                'content': r.content,
                'diagnosis': r.diagnosis
            } for r in resources
        ]
        
        return Response({'resources': data}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error en get_personalized_resources: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Vista para obtener todos los recursos
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_all_resources(request):
    try:
        resources = Resource.objects.all()
        data = [
            {'id': r.id, 'title': r.title, 'type': r.type, 'content': r.content, 'diagnosis': r.diagnosis}
            for r in resources
        ]
        return Response({'resources': data}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error en get_all_resources: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Vista para crear una nueva meta de bienestar
class CreateWellnessGoalView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        try:
            user = request.user
            title = request.data.get('title')
            progress = request.data.get('progress', 0)
            color = request.data.get('color', 'from-indigo-500-to-purple-600')
            icon = request.data.get('icon', 'Target')
            target_progress = request.data.get('target_progress', 100)
            if not title:
                return Response({'error': 'Title is required'}, status=status.HTTP_400_BAD_REQUEST)
            goal = WellnessGoal.objects.create(
                user=user,
                title=title,
                progress=progress,
                color=color,
                icon=icon,
                target_progress=target_progress
            )
            return Response({
                'goal': {
                    'title': goal.title,
                    'progress': goal.progress,
                    'color': goal.color,
                    'icon': goal.icon,
                    'target_progress': goal.target_progress
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en CreateWellnessGoalView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Vista para actualizar el progreso de una meta
class UpdateGoalProgressView(APIView):
    permission_classes = [IsAuthenticated]
    def put(self, request):
        try:
            user = request.user
            title = request.data.get('title')
            progress = request.data.get('progress')
            if not title or progress is None:
                return Response({'error': 'Title and progress are required'}, status=status.HTTP_400_BAD_REQUEST)
            goal = get_object_or_404(WellnessGoal, user=user, title=title)
            goal.progress = progress
            goal.save()
            return Response({
                'goal': {
                    'title': goal.title,
                    'progress': goal.progress,
                    'color': goal.color,
                    'icon': goal.icon
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en UpdateGoalProgressView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Vista para datos del dashboard
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_data(request):
    try:
        user = request.user
        
        # Estadísticas del usuario
        next_event = CalendarEvent.objects.filter(user=user, start_time__gte=timezone.now()).order_by('start_time').first()
        stats = {
            'nextAppointment': {
                'date': next_event.start_time.isoformat() if next_event else '',
                'type': next_event.type if next_event else ''
            },
            'wellnessDays': calculate_wellness_days(user),
        }
        
        # Historial de estado de ánimo del usuario
        mood_history = Mood.objects.filter(user=user).order_by('-timestamp')[:7]
        mood_history_data = [
            {'mood': m.mood, 'date': m.timestamp.isoformat(), 'description': m.description}
            for m in mood_history
        ]
        
        # Metas de bienestar del usuario
        wellness_goals = WellnessGoal.objects.filter(user=user)
        goals_data = [
            {
                'title': goal.title,
                'progress': goal.progress,
                'color': goal.color,
                'icon': goal.icon,
                'target_progress': goal.target_progress
            } for goal in wellness_goals
        ]
        
        # Terapias del usuario
        miembro_terapias = MiembroTerapia.objects.filter(usuario=user)
        terapias = [mt.terapia for mt in miembro_terapias]
        therapies_data = []
        for terapia in terapias:
            miembros = MiembroTerapia.objects.filter(terapia=terapia)
            # Estados de ánimo de todos los miembros (solo para pareja y familiar)
            shared_moods = []
            if terapia.tipo in ['pareja', 'familiar']:
                for miembro in miembros:
                    miembro_moods = Mood.objects.filter(user=miembro.usuario).order_by('-timestamp')[:7]
                    shared_moods.extend([
                        {
                            'user_id': miembro.usuario.id,
                            'nombre': miembro.usuario.nombre or miembro.usuario.email.split('@')[0],
                            'mood': m.mood,
                            'date': m.timestamp.isoformat(),
                            'description': m.description
                        } for m in miembro_moods
                    ])
            
            therapies_data.append({
                'id': terapia.id,
                'tipo': terapia.tipo,
                'herramientas': terapia.herramientas,
                'miembros_count': miembros.count(),
                'limite_miembros': terapia.limite_miembros,
                'es_lider': MiembroTerapia.objects.filter(terapia=terapia, usuario=user, es_lider=True).exists(),
                'shared_moods': shared_moods if terapia.tipo in ['pareja', 'familiar'] else [],
            })
        
        return Response({
            'stats': stats,
            'moodHistory': mood_history_data,
            'wellnessGoals': goals_data,
            'therapies': therapies_data,
        }, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error en get_dashboard_data: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
# Autenticación y vistas de usuario
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"error": "No se proporcionó el refresh token"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception as e:
            return Response({"error": "Error al invalidar token: " + str(e)}, status=status.HTTP_400_BAD_REQUEST)
        logout(request)
        return Response({"message": "Sesión cerrada correctamente"}, status=status.HTTP_200_OK)

def validate_recaptcha(recaptcha_response):
    url = 'https://www.google.com/recaptcha/api/siteverify'
    payload = {
        'secret': settings.RECAPTCHA_PRIVATE_KEY,
        'response': recaptcha_response
    }
    response = requests.post(url, data=payload)
    result = response.json()
    if not result.get('success', False):
        return False
    score = result.get('score', 0)
    if score < settings.RECAPTCHA_REQUIRED_SCORE:
        return False
    return True

# Función auxiliar para calcular días de bienestar
def calculate_wellness_days(user):
    seven_days_ago = timezone.now() - timedelta(days=7)
    moods = Mood.objects.filter(user=user, timestamp__gte=seven_days_ago).order_by('timestamp')
    wellness_days = 0
    current_day = None
    for mood in moods:
        mood_day = mood.timestamp.date()
        if current_day != mood_day:
            day_moods = Mood.objects.filter(
                user=user,
                timestamp__date=mood_day
            )
            if day_moods.filter(mood__in=['Bien', 'Excelente']).exists():
                wellness_days += 1
            current_day = mood_day
    return wellness_days


class PsychologistRegisterView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser] # Indicar que puede recibir archivos

    def post(self, request, *args, **kwargs): # Añadir *args, **kwargs por estándar
        # request.data contendrá tanto los campos de texto como los archivos
        recaptcha_response = request.data.get('recaptcha_response')

        if not validate_recaptcha(recaptcha_response):
            logger.warning("Psychologist registration failed: Invalid reCAPTCHA")
            return Response({'error': 'Validación de reCAPTCHA fallida'}, status=status.HTTP_400_BAD_REQUEST)

        # Pasar request.data completo al serializer
        serializer = PsychologistRegisterSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save() # El serializer ahora crea Usuario y Perfil
                logger.info(f"Psychologist registered successfully with profile: {user.email}")

                refresh = RefreshToken.for_user(user)

                # Considerar devolver algunos datos del perfil creado si el frontend los necesita de inmediato
                user_data = UserSerializer(user).data # Usar UserSerializer para datos básicos

                return Response({
                    'message': 'Registro de psicóloga exitoso.',
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                    'user': user_data # Devolver datos básicos del usuario
                }, status=status.HTTP_201_CREATED)

            except Exception as e:
                logger.error(f"Error creating psychologist user {request.data.get('email')}: {str(e)}", exc_info=True)
                return Response({'error': 'Ocurrió un error interno al crear la cuenta.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            logger.warning(f"Psychologist registration validation failed: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        recaptcha_response = request.data.get('recaptcha_response')
        token_invitacion = request.data.get('token')

        if not email or not password:
            return Response({'error': 'Email y contraseña son obligatorios'}, status=status.HTTP_400_BAD_REQUEST)

        if not validate_recaptcha(recaptcha_response):
            return Response({'error': 'Validación de reCAPTCHA fallida'}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(email=email, password=password)
        if user:
            login(request, user)
            user.ultima_sesion = timezone.now()
            user.sesiones_completadas += 1
            user.save()
            refresh = RefreshToken.for_user(user)

            if token_invitacion:
                self.procesar_invitacion(user, token_invitacion)

            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'is_psychologist': user.is_psychologist
            }, status=status.HTTP_200_OK)
        return Response({'error': 'Credenciales inválidas'}, status=status.HTTP_401_UNAUTHORIZED)

    def procesar_invitacion(self, user, token):
        try:
            invitacion = InvitacionTerapia.objects.get(token=token, usado=False)
            terapia = invitacion.terapia
            if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                num_miembros = MiembroTerapia.objects.filter(terapia=terapia).count()
                if num_miembros < terapia.limite_miembros:
                    MiembroTerapia.objects.create(usuario=user, terapia=terapia, es_lider=False)
                    invitacion.usado = True
                    invitacion.save()
        except InvitacionTerapia.DoesNotExist:
            pass

class GoogleLogin(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        recaptcha_response = request.data.get('recaptcha_response')
        token_invitacion = request.data.get('token_invitacion')

        if not token:
            return Response({'error': 'Token de Google es requerido'}, status=status.HTTP_400_BAD_REQUEST)

        if not validate_recaptcha(recaptcha_response):
            return Response({'error': 'Validación de reCAPTCHA fallida'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            idinfo = id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']
            )
            email = idinfo['email']
            nombre = idinfo.get('name', '')

            user, created = User.objects.get_or_create(
                email=email,
                defaults={'nombre': nombre, 'tipo_cuenta': 'Google', 'is_new_user': True}
            )
            if created:
                user.set_unusable_password()
                user.save()
                # Enviar correo de bienvenida
                context = {
                    'nombre': user.nombre or user.email.split('@')[0],
                    'dashboard_url': f"{settings.FRONTEND_URL}/dashboard",
                    'year': timezone.now().year,
                }
                success = send_brevo_email(
                    subject="¡Bienvenid@ a Senti!",
                    to_email=user.email,
                    template_name="welcome_email.html",
                    context=context
                )
                if not success:
                    logger.warning(f"No se pudo enviar el correo de bienvenida a {user.email}")

            refresh = RefreshToken.for_user(user)

            if token_invitacion:
                self.procesar_invitacion(user, token_invitacion)

            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'is_psychologist': user.is_psychologist,
                'is_new_user': user.is_new_user  # Añadir esto para el frontend
            }, status=status.HTTP_200_OK)
        except ValueError as e:
            logger.error(f"Error en Google Login: {str(e)}")
            return Response({'error': 'Token de Google inválido'}, status=status.HTTP_400_BAD_REQUEST)

    def procesar_invitacion(self, user, token):
        try:
            invitacion = InvitacionTerapia.objects.get(token=token, usado=False)
            terapia = invitacion.terapia
            if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                num_miembros = MiembroTerapia.objects.filter(terapia=terapia).count()
                if num_miembros < terapia.limite_miembros:
                    MiembroTerapia.objects.create(usuario=user, terapia=terapia, es_lider=False)
                    invitacion.usado = True
                    invitacion.save()
        except InvitacionTerapia.DoesNotExist:
            pass

# views.py
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        recaptcha_response = request.data.get('recaptcha_response')
        token_invitacion = request.data.get('token')

        if not validate_recaptcha(recaptcha_response):
            return Response({'error': 'Validación de reCAPTCHA fallida'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save()
                refresh = RefreshToken.for_user(user)

                # Enviar correo de bienvenida
                context = {
                    'nombre': user.nombre or user.email.split('@')[0],
                    'dashboard_url': f"{settings.FRONTEND_URL}/dashboard",
                    'year': timezone.now().year,
                }
                success = send_brevo_email(
                    subject="¡Bienvenid@ a Senti!",
                    to_email=user.email,
                    template_name="welcome_email.html",
                    context=context
                )
                if not success:
                    logger.warning(f"No se pudo enviar el correo de bienvenida a {user.email}")

                if token_invitacion:
                    self.procesar_invitacion(user, token_invitacion)

                return Response({
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                    'is_psychologist': user.is_psychologist
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                logger.error(f"Error en RegisterView: {str(e)}")
                if "email" in str(e).lower():
                    return Response({'error': 'El email ya está registrado'}, status=status.HTTP_400_BAD_REQUEST)
                return Response({'error': 'Error al crear el usuario'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def procesar_invitacion(self, user, token):
        try:
            invitacion = InvitacionTerapia.objects.get(token=token, usado=False)
            terapia = invitacion.terapia
            if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                num_miembros = MiembroTerapia.objects.filter(terapia=terapia).count()
                if num_miembros < terapia.limite_miembros:
                    MiembroTerapia.objects.create(usuario=user, terapia=terapia, es_lider=False)
                    invitacion.usado = True
                    invitacion.save()
        except InvitacionTerapia.DoesNotExist:
            pass

# views.py
class UserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            usuario = request.user
            user_data = {
                'uid': str(usuario.id),
                'email': usuario.email,
                'nombre': usuario.nombre,
                'telefono': usuario.telefono or '',
                'fecha_registro': usuario.fecha_registro.isoformat(),
                'ultima_sesion': usuario.ultima_sesion.isoformat() if usuario.ultima_sesion else '',
                'tipo_cuenta': usuario.tipo_cuenta,
                'email_notifications': usuario.email_notifications,
                'push_notifications': usuario.push_notifications,
                'dias_activos': usuario.dias_activos,
                'sesiones_completadas': usuario.sesiones_completadas,
                'is_psychologist': usuario.is_psychologist,
                'is_new_user': usuario.is_new_user,
                'gender': usuario.gender
            }
            return Response(user_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en UserView GET: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class UpdateProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        usuario = request.user
        data = request.data

        # Actualizar solo los campos proporcionados
        if 'nombre' in data:
            usuario.nombre = data['nombre']
        if 'telefono' in data:
            usuario.telefono = data['telefono']
        if 'gender' in data:
            usuario.gender = data['gender']
        if 'birthdate' in data:
            usuario.birthdate = data['birthdate'] if data['birthdate'] else None
        if 'country' in data:
            usuario.country = data['country']
        # Permitir actualizar public_likes si se envía
        if 'public_likes' in data:
            try:
                usuario.profile.public_likes = data['public_likes']
                usuario.profile.save()
            except AttributeError:
                logger.warning(f"Usuario {usuario.id} no tiene perfil, creando uno")
                from user_profile.models import UserProfile
                UserProfile.objects.create(user=usuario, public_likes=data['public_likes'])

        try:
            # Validaciones
            if hasattr(usuario, 'nombre') and usuario.nombre and len(usuario.nombre) > 255:
                return Response({'error': 'El nombre no puede exceder los 255 caracteres'}, status=status.HTTP_400_BAD_REQUEST)
            
            if hasattr(usuario, 'telefono') and usuario.telefono and len(usuario.telefono) > 20:
                return Response({'error': 'El teléfono no puede exceder los 20 caracteres'}, status=status.HTTP_400_BAD_REQUEST)
            
            if hasattr(usuario, 'gender') and usuario.gender and usuario.gender not in [choice[0] for choice in Usuario.GENDER_CHOICES]:
                return Response({'error': 'Género inválido'}, status=status.HTTP_400_BAD_REQUEST)
            
            if hasattr(usuario, 'birthdate') and usuario.birthdate:
                try:
                    birthdate = datetime.strptime(str(usuario.birthdate), '%Y-%m-%d').date()
                    today = timezone.now().date()
                    min_birthdate = today.replace(year=today.year - 16)
                    if birthdate > min_birthdate:
                        return Response({'error': 'Debes tener al menos 16 años'}, status=status.HTTP_400_BAD_REQUEST)
                except ValueError:
                    return Response({'error': 'Formato de fecha inválido. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
            
            if hasattr(usuario, 'country') and usuario.country and (len(usuario.country) != 2 or not usuario.country.isalpha()):
                return Response({'error': 'El código de país debe ser de 2 letras (ISO 3166-1 alpha-2)'}, status=status.HTTP_400_BAD_REQUEST)

            # Guardar cambios en el usuario
            usuario.save()

            # Serializar la respuesta
            serializer = UserSerializer(usuario)
            return Response({
                'message': 'Perfil actualizado',
                'user': serializer.data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en UpdateProfileView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
class UpdatePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        usuario = request.user
        password = request.data.get('password')
        if not password:
            return Response({'error': 'La contraseña es obligatoria'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            usuario.set_password(password)
            usuario.save()
            return Response({'message': 'Contraseña actualizada'}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en UpdatePasswordView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class UpdateNotificationPrefsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        usuario = request.user
        email_notifications = request.data.get('email_notifications', usuario.email_notifications)
        push_notifications = request.data.get('push_notifications', usuario.push_notifications)
        try:
            usuario.email_notifications = email_notifications
            usuario.push_notifications = push_notifications
            usuario.save()
            return Response({'message': 'Preferencias actualizadas'}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en UpdateNotificationPrefsView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        usuario = request.user
        try:
            usuario.delete()
            return Response({'message': 'Cuenta eliminada'}, status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            logger.error(f"Error en DeleteAccountView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_info(request):
    user = request.user
    logger.info(f"User info solicitado para {user.email}: is_new_user={user.is_new_user}")

    # Usa el serializer para obtener TODOS los campos definidos en él
    serializer = UserSerializer(user, context={'request': request})

    # Devuelve los datos completos del serializer
    return Response(serializer.data, status=status.HTTP_200_OK)


# Vistas para terapias
# api/views.py
class CrearTerapiaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tipo = request.data.get('tipo')
        nombre_familia = request.data.get('nombre_familia', '')
        rol = request.data.get('rol', '')

        logger.info(f"Datos recibidos en /api/terapia/crear/: {request.data}")

        if not tipo:
            return Response({'error': 'El tipo de terapia es obligatorio'}, status=status.HTTP_400_BAD_REQUEST)

        if tipo not in ['individual', 'pareja', 'familiar']:
            return Response({'error': 'Tipo de terapia inválido'}, status=status.HTTP_400_BAD_REQUEST)

        if tipo == 'familiar' and not nombre_familia:
            return Response({'error': 'El nombre de la familia es obligatorio para terapias familiares'}, status=status.HTTP_400_BAD_REQUEST)

        if tipo == 'familiar':
            valid_roles = [choice[0] for choice in MiembroTerapia.ROLES_FAMILIA]
            if not rol:
                return Response({'error': 'El rol es obligatorio para terapias familiares'}, status=status.HTTP_400_BAD_REQUEST)
            if rol not in valid_roles:
                return Response({'error': f'Rol inválido. Roles válidos: {valid_roles}'}, status=status.HTTP_400_BAD_REQUEST)

        # Configuración de herramientas (sin chat)
           
        herramientas = {
                'individual': {'diario': True, 'progreso_personal': True},
                    'pareja': {'diario': True, 'ejercicios_pareja': True, 'mood_compartido': True},
              'familiar': {'diario': True, 'actividades_familiares': True, 'mood_compartido': True}
            }.get(tipo, {'diario': True})

        

        try:
            terapia = Terapia.objects.create(
                tipo=tipo,
                nombre_familia=nombre_familia if tipo == 'familiar' else None,
                herramientas=herramientas
            )

            miembro_data = {
                'usuario': request.user,
                'terapia': terapia,
                'es_lider': True
            }
            if tipo == 'familiar':
                miembro_data['rol'] = rol

            MiembroTerapia.objects.create(**miembro_data)

            # Crear configuración del chat
            from chat.models import ChatConfig
            chat_habilitado = tipo in ['pareja', 'familiar']  # Chat habilitado para pareja y familiar
            ChatConfig.objects.create(
                terapia=terapia,
                chat_habilitado=chat_habilitado
            )

            serializer = TerapiaSerializer(terapia)
            logger.info(f"Terapia creada con ID: {terapia.id}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error creando terapia: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GenerarInvitacionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, terapia_id):
        try:
            # Usar 'terapia_id' en lugar de '_id'
            terapia = Terapia.objects.get(id=terapia_id)
            miembro = MiembroTerapia.objects.get(terapia=terapia, usuario=request.user)
            
            if not miembro.es_lider:
                return Response(
                    {'error': 'Solo el líder puede generar invitaciones'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            token = str(uuid.uuid4())
            invitacion = InvitacionTerapia.objects.create(
                terapia=terapia,
                token=token,
                creado_por=request.user  # Corregido 'creado_por' a 'creada_por' si el modelo lo requiere
            )
            enlace = f"{settings.FRONTEND_URL}/invitacion/{token}"
            
            logger.info(f"Invitación generada para terapia {terapia_id} por {request.user.email}")
            return Response({'enlace': enlace}, status=status.HTTP_201_CREATED)
        
        except Terapia.DoesNotExist:
            logger.error(f"Terapia con ID {terapia_id} no encontrada")
            return Response({'error': 'Terapia no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except MiembroTerapia.DoesNotExist:
            logger.error(f"El usuario {request.user.email} no es miembro de la terapia {terapia_id}")
            return Response({'error': 'No eres miembro de esta terapia'}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.error(f"Error en GenerarInvitacionView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class UnirseTerapiaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get('token')
        rol = request.data.get('rol', '')

        logger.info(f"Datos recibidos en /api/terapia/unirse/: {request.data}")

        if not token:
            return Response({'error': 'Token requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            invitacion = InvitacionTerapia.objects.get(token=token, usado=False)
            terapia = invitacion.terapia

            if terapia.tipo == 'familiar':
                valid_roles = [choice[0] for choice in MiembroTerapia.ROLES_FAMILIA]
                if not rol:
                    return Response({'error': 'El rol es obligatorio para terapias familiares'}, status=status.HTTP_400_BAD_REQUEST)
                if rol not in valid_roles:
                    return Response({'error': f'Rol inválido. Roles válidos: {valid_roles}'}, status=status.HTTP_400_BAD_REQUEST)
                miembro_data = {
                    'usuario': request.user,
                    'terapia': terapia,
                    'es_lider': False,
                    'rol': rol
                }
            else:
                miembro_data = {
                    'usuario': request.user,
                    'terapia': terapia,
                    'es_lider': False
                }

            if MiembroTerapia.objects.filter(usuario=request.user, terapia=terapia).exists():
                return Response({'error': 'Ya eres miembro de esta terapia'}, status=status.HTTP_400_BAD_REQUEST)

            num_miembros = MiembroTerapia.objects.filter(terapia=terapia).count()
            if num_miembros >= terapia.limite_miembros:
                return Response({'error': 'La terapia ha alcanzado el límite de miembros'}, status=status.HTTP_400_BAD_REQUEST)

            MiembroTerapia.objects.create(**miembro_data)
            invitacion.usado = True
            invitacion.save()
            logger.info(f"Usuario {request.user.email} se unió a la terapia {terapia.id}")
            return Response({
                'message': 'Te has unido a la terapia exitosamente',
                'terapia_id': terapia.id
            }, status=status.HTTP_200_OK)
        except InvitacionTerapia.DoesNotExist:
            return Response({'error': 'Invitación inválida o ya usada'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error uniéndose a terapia: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ListarTerapiasView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            miembro_terapias = MiembroTerapia.objects.filter(usuario=request.user).select_related('terapia')
            terapias = [mt.terapia for mt in miembro_terapias]
            serializer = TerapiaSerializer(terapias, many=True)
            
            terapias_data = serializer.data
            for terapia in terapias_data:
                terapia['fecha_creacion'] = terapia.get('fecha_creacion', timezone.now().isoformat())
                terapia['miembros_count'] = MiembroTerapia.objects.filter(terapia__id=terapia['id']).count()
                terapia['limite_miembros'] = terapias[0].limite_miembros if terapias else 1
                terapia['es_lider'] = MiembroTerapia.objects.filter(
                    terapia__id=terapia['id'], usuario=request.user, es_lider=True
                ).exists()
                # Añadir chat_habilitado
                try:
                    chat_config = ChatConfig.objects.get(terapia__id=terapia['id'])
                    terapia['chat_habilitado'] = chat_config.chat_habilitado
                    logger.debug(f"ChatConfig para terapia {terapia['id']}: chat_habilitado={chat_config.chat_habilitado}")
                except ChatConfig.DoesNotExist:
                    terapia['chat_habilitado'] = False
                    logger.warning(f"No se encontró ChatConfig para terapia {terapia['id']}")
                # Lista de miembros
                miembros = MiembroTerapia.objects.filter(terapia__id=terapia['id']).select_related('usuario')
                terapia['miembros'] = [
                    {
                        'id': miembro.usuario.id,
                        'nombre': miembro.usuario.nombre if hasattr(miembro.usuario, 'nombre') else miembro.usuario.email.split('@')[0],
                        'es_lider': miembro.es_lider
                    } for miembro in miembros
                ]
            
            logger.info(f"Terapias devueltas para usuario {request.user.email}: {len(terapias_data)} terapias")
            return Response(terapias_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en ListarTerapiasView: {str(e)}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
# api/views.py
class DetalleTerapiaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, terapia_id):
        try:
            miembro = get_object_or_404(MiembroTerapia, usuario=request.user, terapia__id=terapia_id)
            terapia = miembro.terapia

            miembros_query = MiembroTerapia.objects.filter(terapia=terapia).select_related('usuario')
            miembro_user_ids = list(miembros_query.values_list('usuario_id', flat=True))

            completed_assessments_count = InitialAssessment.objects.filter(
                user_id__in=miembro_user_ids,
                completed=True
            ).count()

            # Obtener configuración del chat
            try:
                chat_config = ChatConfig.objects.get(terapia=terapia)
                chat_habilitado = chat_config.chat_habilitado
            except ChatConfig.DoesNotExist:
                chat_habilitado = False  # Por defecto, si no hay configuración

            response_data = {
                'id': terapia.id,
                'tipo': terapia.tipo,
                'nombre_familia': terapia.nombre_familia,
                'combined_diagnosis': terapia.combined_diagnosis,
                'miembros': [
                    {
                        'id': m.usuario.id,
                        'email': m.usuario.email,
                    }
                    for m in miembros_query
                ],
                'limite_miembros': terapia.limite_miembros,
                'completed_assessments_count': completed_assessments_count,
                'chat_habilitado': chat_habilitado,  # Nueva propiedad
                'herramientas': terapia.herramientas,  # Mantener otras herramientas
            }
            logger.info(f"Detalles de terapia devueltos para {terapia_id}")
            return Response(response_data, status=status.HTTP_200_OK)
        except Terapia.DoesNotExist:
            logger.error(f"Terapia con ID {terapia_id} no encontrada o usuario no es miembro")
            return Response({'error': 'Terapia no encontrada o no eres miembro'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error en DetalleTerapiaView para Terapia ID {terapia_id}: {str(e)}", exc_info=True)
            return Response({'error': f'Error interno del servidor: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        
class GetPsychologistAvailabilityView(APIView):
    """
    API View para obtener los horarios disponibles de psicólogos para una fecha dada.

    Permite filtrar por psicólogos que ofrecen sesiones gratuitas y devolver una
    respuesta detallada (por psicólogo) o un rango general.

    Parámetros Query:
        - date (str): Fecha requerida en formato 'YYYY-MM-DD'. Obligatorio.
        - detailed (bool, opcional): Si 'true', devuelve slots por psicólogo. Default 'false'.
        - free_session_only (bool, opcional): Si 'true', filtra por psicólogos que ofrecen
                                              sesiones gratuitas. Default 'false'.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Obtener parámetros de la solicitud
            date_str = request.query_params.get('date')
            detailed = request.query_params.get('detailed', 'false').lower() == 'true'
            free_session_only = request.query_params.get('free_session_only', 'false').lower() == 'true'

            # Validar que se haya proporcionado la fecha
            if not date_str:
                return Response(
                    {'error': 'Parámetro "date" (YYYY-MM-DD) es requerido.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Parsear y validar el formato de la fecha
            try:
                requested_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Formato de fecha inválido. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Obtener fecha/hora actual y el inicio del día solicitado
            now_aware = timezone.now()
            requested_datetime_start = timezone.make_aware(datetime.combine(requested_date, datetime.min.time()))

            # Prevenir consultas de fechas pasadas
            if requested_datetime_start.date() < now_aware.date():
                return Response(
                    {'error': 'No se puede consultar disponibilidad para fechas pasadas.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Filtrar psicólogos activos
            psychologists_query = Usuario.objects.filter(is_psychologist=True, is_active=True)

            # Aplicar filtro de sesiones gratuitas si se solicita
            if free_session_only:
                try:
                    # Ajusta este campo según tu modelo (ejemplo: relación con perfil o campo directo)
                    filter_field = 'psychologist_profile__offers_free_30min_session'
                    psychologists_query = psychologists_query.filter(**{filter_field: True})
                except FieldError:
                    logger.warning(f"No se pudo aplicar el filtro '{filter_field}'. Verifica el modelo.")
                    pass  # Continúa sin filtro si falla

            # Optimizar consulta con prefetch_related
            psychologists = psychologists_query.prefetch_related('availability')

            # Si no hay psicólogos disponibles
            if not psychologists.exists():
                logger.info(f"No se encontraron psicólogos activos{' con sesiones gratuitas' if free_session_only else ''}.")
                return Response(
                    {'available_slots': []} if detailed else {'start': '', 'end': ''},
                    status=status.HTTP_200_OK
                )

            # Obtener el día de la semana en minúsculas (formato inglés)
            try:
                day_of_week_for_query = requested_date.strftime('%A').lower()  # ej: 'monday', 'tuesday'
            except Exception as e:
                logger.error(f"Error al obtener el día de la semana: {e}")
                return Response(
                    {'error': 'Error interno al determinar el día.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Calcular slots disponibles por psicólogo
            available_slots_by_psychologist = {}
            slot_duration = timedelta(minutes=30)

            for psychologist in psychologists:
                # Buscar disponibilidad para el día solicitado
                availability = Availability.objects.filter(
                    psychologist=psychologist,
                    day_of_week__iexact=day_of_week_for_query
                ).first()

                if not availability or not availability.start_time or not availability.end_time:
                    continue

                # Convertir horas a datetimes conscientes de zona horaria
                start_dt = timezone.make_aware(datetime.combine(requested_date, availability.start_time))
                end_dt = timezone.make_aware(datetime.combine(requested_date, availability.end_time))

                # Ajustar hora de inicio si es hoy
                current_slot_start = start_dt
                if requested_date == now_aware.date():
                    min_start_time = now_aware + timedelta(minutes=60)  # Margen de 60 minutos
                    if min_start_time > current_slot_start:
                        current_slot_start = min_start_time

                # Redondear la hora de inicio al próximo múltiplo de 30 minutos
                if current_slot_start.minute % 30 != 0 or current_slot_start.second != 0 or current_slot_start.microsecond != 0:
                    minutes_to_add = 30 - (current_slot_start.minute % 30)
                    current_slot_start = (current_slot_start + timedelta(minutes=minutes_to_add)).replace(second=0, microsecond=0)
                    current_slot_start = current_slot_start.replace(minute=(current_slot_start.minute // 30) * 30)

                # Generar slots y verificar conflictos
                valid_slots = []
                while current_slot_start < end_dt:
                    slot_end = current_slot_start + slot_duration
                    if slot_end > end_dt:
                        break

                    # Verificar conflictos con eventos existentes
                    has_conflict = CalendarEvent.objects.filter(
                        psychologist=psychologist,
                        start_time__lt=slot_end,
                        end_time__gt=current_slot_start
                    ).exists()

                    if not has_conflict:
                        valid_slots.append(current_slot_start.strftime('%H:%M'))

                    current_slot_start += slot_duration

                # Guardar slots válidos para este psicólogo
                if valid_slots:
                    available_slots_by_psychologist[psychologist.id] = {
                        'psychologist': {
                            'id': psychologist.id,
                            'nombre': psychologist.nombre,
                            'email': psychologist.email
                        },
                        'slots': valid_slots
                    }

            # Si no hay slots disponibles
            if not available_slots_by_psychologist:
                logger.info(f"No hay slots disponibles para {date_str} con los filtros aplicados.")
                return Response(
                    {'available_slots': []} if detailed else {'start': '', 'end': ''},
                    status=status.HTTP_200_OK
                )

            # Formatear respuesta según el parámetro 'detailed'
            if detailed:
                return Response(
                    {'available_slots': list(available_slots_by_psychologist.values())},
                    status=status.HTTP_200_OK
                )
            else:
                all_slots = []
                for data in available_slots_by_psychologist.values():
                    all_slots.extend(data['slots'])
                if not all_slots:
                    return Response({'start': '', 'end': ''}, status=status.HTTP_200_OK)
                all_slots.sort()
                return Response(
                    {'start': all_slots[0], 'end': all_slots[-1]},
                    status=status.HTTP_200_OK
                )

        except Exception as e:
            logger.exception(f"Error inesperado en GetPsychologistAvailabilityView para fecha {date_str}: {e}")
            return Response(
                {'error': 'Ocurrió un error interno al procesar la solicitud de disponibilidad.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# sesion gratis
class ScheduleFreeSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            date_str = request.data.get('date')
            time_str = request.data.get('time')
            terapia_id = request.data.get('terapia_id')
            psychologist_id = request.data.get('psychologist_id')

            if not date_str or not time_str or not psychologist_id:
                return Response({'error': 'Se requiere fecha, hora y ID de psicóloga'}, status=status.HTTP_400_BAD_REQUEST)

            # Verificar si el usuario ya tiene una sesión gratuita
            has_free_session = CalendarEvent.objects.filter(
                user=user,
                title="Sesión Gratuita de Terapia",
                type='therapy'
            ).exists()
            if has_free_session:
                return Response({'error': 'Ya has programado tu sesión gratuita'}, status=status.HTTP_403_FORBIDDEN)

            # Convertir fecha y hora a datetime aware
            requested_datetime_naive = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
            requested_datetime = timezone.make_aware(requested_datetime_naive)
            session_duration = timedelta(minutes=30)
            end_datetime = requested_datetime + session_duration

            # Validar que la sesión sea al menos 1 hora después de ahora
            now = timezone.now()
            min_allowed_time = now + timedelta(hours=1)
            if requested_datetime < min_allowed_time:
                return Response(
                    {'error': 'La sesión debe programarse al menos 1 hora después de la hora actual'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Obtener psicóloga seleccionada
            psychologist = get_object_or_404(
                Usuario,
                id=psychologist_id,
                is_psychologist=True,
                psychologist_profile__offers_free_30min_session=True
            )

            # Verificar disponibilidad
            day_of_week = requested_datetime.strftime('%A')
            availability = Availability.objects.filter(
                psychologist=psychologist,
                day_of_week=day_of_week
            ).first()

            if not availability:
                return Response({'error': f"La psicóloga {psychologist.nombre} no está disponible ese día"}, status=status.HTTP_400_BAD_REQUEST)

            start_time = timezone.make_aware(
                datetime.combine(requested_datetime.date(), availability.start_time)
            )
            end_time = timezone.make_aware(
                datetime.combine(requested_datetime.date(), availability.end_time)
            )

            if not (start_time <= requested_datetime < end_time - session_duration):
                return Response({'error': 'La hora seleccionada no está dentro del horario disponible'}, status=status.HTTP_400_BAD_REQUEST)

            if requested_datetime.minute % 30 != 0:
                return Response({'error': 'La hora debe estar en intervalos de 30 minutos'}, status=status.HTTP_400_BAD_REQUEST)

            # Verificar conflictos
            conflicts = CalendarEvent.objects.filter(
                psychologist=psychologist,
                type__in=['therapy', 'group'],
                start_time__lt=end_datetime,
                end_time__gt=requested_datetime
            ).exists()

            if conflicts:
                return Response({'error': 'El horario seleccionado no está disponible'}, status=status.HTTP_409_CONFLICT)

            # Manejar la terapia
            if terapia_id:
                terapia = Terapia.objects.get(id=terapia_id)
                if not MiembroTerapia.objects.filter(usuario=user, terapia=terapia).exists():
                    return Response({'error': 'No eres miembro de esta terapia'}, status=status.HTTP_403_FORBIDDEN)
            else:
                terapia = Terapia.objects.filter(miembroterapia__usuario=user).order_by('-fecha_creacion').first()
                if not terapia:
                    terapia = Terapia.objects.create(
                        tipo='individual',
                        herramientas={'diario': True, 'progreso_personal': True}  # Sin 'chat'
                    )
                    MiembroTerapia.objects.create(usuario=user, terapia=terapia, es_lider=True)
                    # Crear configuración del chat
                    ChatConfig.objects.create(
                        terapia=terapia,
                        chat_habilitado=False  # Chat deshabilitado para individual
                    )

            # Crear el evento
            event = CalendarEvent.objects.create(
                user=user,
                event_id=f"free_{timezone.now().timestamp()}_{user.id}",
                title="Sesión Gratuita de Terapia",
                start_time=requested_datetime,
                end_time=end_datetime,
                type='therapy',
                psychologist=psychologist,
                description=f"Sesión gratuita inicial de 30 minutos con {psychologist.nombre}",
                terapia=terapia
            )

            logger.info(f"Terapia gratuita programada para {user.email} el {requested_datetime} con {psychologist.nombre}")
            return Response({
                'message': 'Sesión gratuita programada con éxito',
                'session': {
                    'id': event.event_id,
                    'title': event.title,
                    'start_time': event.start_time.isoformat(),
                    'end_time': event.end_time.isoformat(),
                    'type': event.type,
                    'terapia_id': terapia.id,
                    'psychologist': {
                        'id': psychologist.id,
                        'nombre': psychologist.nombre,
                        'email': psychologist.email,
                        'profile_pic': psychologist.profile_pic.url if psychologist.profile_pic else None
                    }
                }
            }, status=status.HTTP_201_CREATED)

        except ValueError:
            return Response({'error': 'Formato de fecha u hora inválido'}, status=status.HTTP_400_BAD_REQUEST)
        except Terapia.DoesNotExist:
            return Response({'error': 'Terapia no encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error en ScheduleFreeSessionView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# therapy/serializers.py
from rest_framework import serializers
from django.conf import settings
from django.utils import timezone # Necesario para comparar reveal_date

from .models import (
    Category, InitialScreeningAssessment, EmotionalProfile, Challenge,
    EmotionalPath, UserChallenge, UserPathProgress, DailyComponent
)
from api.models import Terapia, MiembroTerapia # Asumiendo que están aquí
from django.contrib.auth import get_user_model

# Importar las funciones de utilidad R2
from .utils.r2_storage import generate_presigned_url, get_object_key_from_url
import logging # Para logging opcional

User = get_user_model()
logger = logging.getLogger(__name__) # Logger para este módulo

# Definición de las preguntas (SIN CAMBIOS)
QUESTIONS = {
    # ... (tu diccionario QUESTIONS) ...
    1: { "text": "¿Con qué frecuencia te sientes abrumado por preocupaciones que no puedes control?", "categories": {"Ansiedad": 3, "Estrés": 2, "Manejo emocional": 1}},
    2: { "text": "¿Sientes que tu confianza en ti mismo afecta tus decisiones o relaciones diarias?", "categories": {"Autoestima": 3, "Habilidades sociales": 2, "Relaciones de pareja": 1}},
    3: { "text": "¿Con qué frecuencia te sientes atrapado en pensamientos negativos o rumiaciones?", "categories": {"Depresión": 3, "Ansiedad": 2, "Trauma": 1}},
    4: { "text": "¿Tienes dificultades para dormir o descansar adecuadamente por razones emocionales o mentales?", "categories": {"Estrés": 3, "Problemas de sueño": 3, "Ansiedad": 1}},
    5: { "text": "¿Te resulta difícil manejar tus emociones intensas como la ira, tristeza o frustración?", "categories": {"Manejo emocional": 3, "Impulsividad": 2, "Autoestima": 1}},
    6: { "text": "¿Sientes que has perdido motivación o propósito en tu vida reciente?", "categories": {"Motivación": 3, "Depresión": 2, "Crisis existencial": 1}},
    7: { "text": "¿Tienes problemas para comunicarte abiertamente con personas cercanas a ti?", "categories": {"Comunicación": 3, "Relaciones de pareja": 2, "Familia y crianza": 1}},
    8: { "text": "¿Evitas situaciones sociales o sientes incomodidad al interactuar con los demás?", "categories": {"Habilidades sociales": 3, "Ansiedad": 2, "Autoestima": 1}},
    9: { "text": "¿Sientes que cargas con heridas emocionales del pasado que afectan tu presente?", "categories": {"Trauma": 3, "Reencuentro con uno mismo": 2, "Depresión": 1}},
    10: {"text": "¿Te cuesta adaptarte a los cambios o sientes miedo ante lo nuevo?", "categories": {"Manejo del cambio": 3, "Ansiedad": 2, "Impulsividad": 1}},
    11: {"text": "¿Tienes pensamientos autocríticos o te juzgas constantemente?", "categories": {"Autoestima": 3, "Depresión": 2, "Prevención del suicidio": 1}},
    12: {"text": "¿Tienes conflictos recurrentes con tu familia o sientes tensión en casa?", "categories": {"Familia y crianza": 3, "Manejo emocional": 2, "Comunicación": 1}},
    13: {"text": "¿Tienes dificultades para disfrutar de actividades que antes te gustaban?", "categories": {"Depresión": 3, "Motivación": 2, "Estrés": 1}},
    14: {"text": "¿Sientes que no te entiendes a ti mismo o que has perdido tu identidad?", "categories": {"Identidad": 3, "Reencuentro con uno mismo": 2, "Crisis existencial": 1}},
    15: {"text": "¿Te cuesta mantener hábitos saludables como alimentación, sueño o ejercicio?", "categories": {"Trastornos de alimentación": 3, "Impulsividad": 2, "Estrés": 1}},
}

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'description']

class ChallengeSerializer(serializers.ModelSerializer):
    # Incluir la categoría serializada en la respuesta de lectura
    category = CategorySerializer(read_only=True)
    # Permitir asignar por ID al crear/actualizar un Challenge (si lo haces vía API)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True, required=False
    )
    # Asegurarse que 'tools' se incluya
    tools = serializers.CharField(max_length=15) # Ajustar max_length si es necesario

    class Meta:
        model = Challenge
        fields = [
            'id', 'category', 'category_id', 'title', 'description', 'instructions',
            'level', 'type', 'component_frontend', 'mode_collaborative',
            'duration_minutes', 'created_at', 'tools', 'reveal_after_days'
        ]

class EmotionalPathSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True
    )
    # Incluir el usuario para claridad, aunque sea read-only
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    # Incluir terapia, puede ser null
    terapia = serializers.PrimaryKeyRelatedField(read_only=True)


    class Meta:
        model = EmotionalPath
        fields = ['id', 'user', 'terapia', 'category', 'category_id', 'level', 'is_active', 'created_at', 'updated_at']

# ===========================================================
# --- UserChallengeSerializer MODIFICADO ---
# ===========================================================
class UserChallengeSerializer(serializers.ModelSerializer):
    # Serializador anidado para mostrar detalles del reto
    challenge = ChallengeSerializer(read_only=True)
    # Campo para recibir ID del reto al crear/actualizar (si fuera necesario, pero lo manejamos en la vista POST)
    challenge_id = serializers.PrimaryKeyRelatedField(
        queryset=Challenge.objects.all(), source='challenge', write_only=True, required=False
    )
    # Campo para recibir email al crear reto colaborativo (si usaras este serializer para eso)
    collaborative_recipient_email = serializers.EmailField(write_only=True, required=False, allow_null=True)

    # *** NUEVO: Campo para el contenido procesado con URL prefirmada ***
    processed_content = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = UserChallenge
        fields = [
            'id',                   # ID del UserChallenge
            'user',                 # ID del usuario (podría ser un serializer anidado simple si quieres el email)
            'terapia',              # ID de la terapia (podría ser un serializer anidado simple)
            'challenge',            # Detalles completos del reto base (read-only)
            'challenge_id',         # ID del reto base (write-only, opcional en lectura)
            'assigned_at',
            'completed_at',
            'is_completed',
            'collaborative_recipient', # ID del destinatario (podría ser anidado)
            'collaborative_recipient_email', # write-only
            'available_date',
            'reveal_date',
            'content',              # Contenido original guardado (puede tener URL base R2)
            'processed_content',    # *** NUEVO CAMPO CON URL PREFIRMADA Y LÓGICA DE REVELACIÓN ***
        ]
        # Campos que generalmente no se establecen directamente al serializar para crear/actualizar
        read_only_fields = ('user', 'terapia', 'challenge', 'assigned_at', 'completed_at',
                            'is_completed', 'collaborative_recipient', 'available_date',
                            'reveal_date', 'content', 'processed_content')

    def get_processed_content(self, obj: UserChallenge):
        """
        Procesa el campo 'content'.
        - Genera una URL prefirmada si existe 'file_url' y 'storage' == 'r2'.
        - Oculta campos sensibles ('reflection', 'letter') si 'reveal_date' es futuro.
        - Devuelve el diccionario procesado o el contenido original si no es aplicable.
        """
        original_content = obj.content
        if not original_content or not isinstance(original_content, dict):
            return original_content # Devuelve null, vacío o lo que sea que haya

        # Copiar para no modificar el objeto original en memoria
        processed_content = original_content.copy()
        is_sensitive = obj.challenge and obj.challenge.tools in ['reflection', 'letter'] # Chequear si el reto existe
        reveal_date = obj.reveal_date
        now_date = timezone.now().date()

        # 1. Procesar URL prefirmada
        file_url = original_content.get('file_url')
        storage = original_content.get('storage')
        if file_url and storage == 'r2':
            object_key = get_object_key_from_url(file_url)
            if object_key:
                # Generar URL válida por 1 hora (ajusta según necesidad)
                presigned_url = generate_presigned_url(settings.AWS_STORAGE_BUCKET_NAME, object_key, expiration=3600)
                if presigned_url:
                    processed_content['presigned_url'] = presigned_url
                    # Opcional: Podrías quitar la URL base para no confundir
                    # processed_content.pop('file_url', None)
                else:
                    processed_content['presigned_url'] = None # Indicar explícitamente que falló
                    processed_content['error'] = "No se pudo generar la URL de acceso al archivo."
                    logger.warning(f"Fallo al generar presigned URL para UserChallenge {obj.id}, key: {object_key}")
            else:
                processed_content['presigned_url'] = None
                processed_content['error'] = "No se pudo determinar la clave del archivo desde la URL guardada."
                logger.warning(f"No se pudo extraer object_key de {file_url} para UserChallenge {obj.id}")

        # 2. Ocultar contenido sensible si aplica y la fecha de revelación es futura
        if is_sensitive and reveal_date and reveal_date > now_date:
            reveal_msg = f"(Contenido disponible el {reveal_date.strftime('%d/%m/%Y')})"
            if 'reflection' in processed_content:
                processed_content['reflection_hidden'] = True # Indicador para el frontend
                processed_content['reflection'] = reveal_msg # Reemplazar con mensaje
            if 'letter' in processed_content:
                processed_content['letter_hidden'] = True # Indicador para el frontend
                processed_content['letter'] = reveal_msg # Reemplazar con mensaje
                # También ocultar destinatario si lo hubiera y es sensible
                # if 'recipient' in processed_content:
                #     processed_content['recipient'] = "(Oculto)"

        return processed_content

    # def validate(self, attrs): ... # Tu validación existente para colaborativo

# ===========================================================
# --- FIN DE UserChallengeSerializer MODIFICADO ---
# ===========================================================

class UserPathProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPathProgress
        fields = ['id', 'user', 'terapia', 'current_level', 'completed_challenges', 'last_level_up', 'updated_at']
        read_only_fields = fields # Normalmente el progreso se lee, no se crea/actualiza vía API directa

class DailyComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyComponent
        fields = ['id', 'user', 'terapia', 'component_type', 'completed_at', 'date']
        read_only_fields = ('user', 'terapia', 'completed_at', 'date') # Tipo es lo único que se podría enviar

class ScreeningResponseItemSerializer(serializers.Serializer):
    question_id = serializers.IntegerField(min_value=1, max_value=len(QUESTIONS), required=True)
    score = serializers.IntegerField(min_value=0, max_value=4, required=True)

class InitialScreeningAssessmentSerializer(serializers.ModelSerializer):
    # --- Tu Serializer de Evaluación Inicial (SIN CAMBIOS NECESARIOS AQUÍ) ---
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    responses = ScreeningResponseItemSerializer(many=True, required=True)
    therapy_type = serializers.ChoiceField(
        choices=[('individual', 'Individual'), ('couple', 'Pareja'), ('family', 'Familiar')],
        default='individual'
    )

    class Meta:
        model = InitialScreeningAssessment
        fields = ['id', 'user', 'terapia', 'therapy_type', 'responses', 'scores', 'completed', 'created_at']
        read_only_fields = ('scores', 'completed', 'created_at') # Estos se calculan en el create

    def validate(self, attrs):
        request = self.context.get('request')
        if not request:
             # Esto no debería pasar en una vista DRF normal, pero por seguridad
             raise serializers.ValidationError("Contexto de request no disponible.")

        # Usar request.data para obtener terapia_id enviado en el POST
        terapia_id_str = request.data.get('terapia') # Viene como string del form/json
        user = attrs.get('user') # Ya establecido por HiddenField(default=...)
        therapy_type = attrs.get('therapy_type')

        if not terapia_id_str:
            raise serializers.ValidationError({"terapia": "Se requiere el ID de la terapia."})

        try:
            terapia_id = int(terapia_id_str)
            terapia = Terapia.objects.get(id=terapia_id)
            if not MiembroTerapia.objects.filter(terapia=terapia, usuario=user).exists():
                raise serializers.ValidationError({"terapia": "No eres miembro de esta terapia."})
            attrs['terapia'] = terapia # Asignar el objeto Terapia validado
        except (ValueError, TypeError):
             raise serializers.ValidationError({"terapia": "ID de terapia inválido."})
        except Terapia.DoesNotExist:
            raise serializers.ValidationError({"terapia": "Terapia no encontrada."})

        # Verificar duplicados
        if InitialScreeningAssessment.objects.filter(
            user=user, terapia=attrs['terapia'], therapy_type=therapy_type
        ).exists():
            raise serializers.ValidationError({"detail": "Ya completaste esta evaluación para esta terapia y tipo."})

        # Validar respuestas
        responses = attrs.get('responses', [])
        num_questions = len(QUESTIONS)
        if len(responses) != num_questions:
            raise serializers.ValidationError({"responses": f"Debes responder exactamente {num_questions} preguntas."})

        # Validar IDs de preguntas
        submitted_q_ids = {r['question_id'] for r in responses}
        expected_q_ids = set(QUESTIONS.keys())
        if submitted_q_ids != expected_q_ids:
             missing = expected_q_ids - submitted_q_ids
             extra = submitted_q_ids - expected_q_ids
             errors = []
             if missing: errors.append(f"Faltan respuestas para preguntas: {sorted(list(missing))}")
             if extra: errors.append(f"IDs de pregunta inválidos o duplicados: {sorted(list(extra))}")
             raise serializers.ValidationError({"responses": ". ".join(errors)})

        # Validar rango de puntaje (aunque ya está en el ItemSerializer)
        for r in responses:
            if not (0 <= r['score'] <= 4):
                 raise serializers.ValidationError({"responses": f"El puntaje para la pregunta {r['question_id']} debe estar entre 0 y 4."})


        return attrs

    def create(self, validated_data):
        responses_data = validated_data.pop('responses')
        user = validated_data['user']
        terapia = validated_data['terapia']
        therapy_type = validated_data['therapy_type']

        # Calcular puntajes por categoría
        category_scores = {}
        for question_id, info in QUESTIONS.items():
             for category_name in info['categories']:
                 category_scores.setdefault(category_name, 0)

        # Mapear respuestas por question_id para fácil acceso
        response_map = {r['question_id']: r['score'] for r in responses_data}

        for question_id, info in QUESTIONS.items():
            score = response_map.get(question_id, 0) # Obtener puntaje de la respuesta
            for category_name, weight in info['categories'].items():
                category_scores[category_name] += score * weight

        # Guardar el objeto Assessment
        assessment = InitialScreeningAssessment.objects.create(
            user=user,
            terapia=terapia,
            therapy_type=therapy_type,
            responses={str(r['question_id']): r['score'] for r in responses_data}, # Guardar como dict
            scores=category_scores, # Guardar puntajes calculados
            completed=True
        )
        logger.info(f"Evaluación inicial (ID: {assessment.id}) creada para {user.email} en terapia {terapia.id}.")

        # Crear o actualizar el perfil emocional asociado
        profile, created = EmotionalProfile.objects.update_or_create(
            user=user,
            terapia=terapia,
            therapy_type=therapy_type,
            defaults={
                'scores': { # Estructura de prioridades
                     'high_priority': [cat for cat, score in category_scores.items() if score > 30], # Ajusta umbrales si es necesario
                     'moderate_priority': [cat for cat, score in category_scores.items() if 15 <= score <= 30],
                     'low_priority': [cat for cat, score in category_scores.items() if score < 15]
                 },
                 'updated_at': timezone.now() # Actualizar timestamp
            }
        )
        log_action = "creado" if created else "actualizado"
        logger.info(f"Perfil emocional (ID: {profile.id}) {log_action} para {user.email} en terapia {terapia.id}.")


        # Devolver la instancia creada del Assessment
        return assessment
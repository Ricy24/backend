# backend/ml_service.py
import os
import pathlib
from dotenv import load_dotenv
import django
import tempfile
from typing import List, Dict, Optional, Tuple
import logging
import threading # Importar threading para el Lock
from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from asgiref.sync import sync_to_async
import edge_tts
import asyncio
import shutil
import uuid
import requests
import whisper # Mantener el import de whisper
import random
import time

# --- Configuración del Logger ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Cargar .env ---
current_script_dir = pathlib.Path(__file__).parent
dotenv_path = current_script_dir.parent / '.env'
if dotenv_path.is_file():
    logger.info(f"Cargando variables de entorno desde: {dotenv_path}")
    load_dotenv(dotenv_path=dotenv_path)
else:
    logger.warning(f"No se encontró el archivo .env en {dotenv_path}.")

# --- Configuración de Django ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
try:
    django.setup()
    from api.models import Usuario
    logger.info("Configuración de Django completada y modelos importados.")
except Exception as e:
    logger.critical(f"ERROR CRÍTICO durante django.setup(): {e}", exc_info=True)
    import sys
    sys.exit("Fallo al iniciar Django. Saliendo.")

# --- Configuración de FastAPI ---
app = FastAPI()
origins = [
    "https://app.senti.lat",
    "https://www.senti.lat",
    "http://localhost:3000",
    "http://localhost:5174",
]
logger.info(f"Configurando CORS para los orígenes: {origins}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Meditation-Session-Id", "X-Meditation-Finished"]
)

# --- Configuración de APIs y Modelos (SIN CARGAR WHISPER AÚN) ---
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY no encontrada.")

# --- Modelos Groq y Límites ---
GROQ_MODELS = [
    {"name": "llama-3.1-8b-instant", "rpm": 30, "tpm": 14400},
    {"name": "llama3-8b-8192", "rpm": 30, "tpm": 6000},
]
model_usage = {model["name"]: {"requests": 0, "tokens": 0, "last_reset": time.time()} for model in GROQ_MODELS}

# --- Estado Global ---
meditation_sessions: Dict[str, Dict] = {}
chat_history: Dict[str, List[Dict[str, str]]] = {}

# --- Variable global y lock para el modelo Whisper (OPTIMIZACIÓN) ---
_whisper_model_instance = None
_whisper_model_load_lock = threading.Lock()

# --- Constantes ---
MAX_MEDITATION_STEPS = 8
DEFAULT_VOICE = "es-ES-AlvaroNeural"
MAX_CHAT_HISTORY_TURNS = 10

# --- FUNCIÓN PARA OBTENER/CARGAR EL MODELO WHISPER (OPTIMIZACIÓN) ---
def get_whisper_model_service():
    """
    Obtiene la instancia global del modelo Whisper para este servicio,
    cargándola si es necesario. Es thread-safe.
    """
    global _whisper_model_instance
    if _whisper_model_instance is None:
        with _whisper_model_load_lock:
            # Doble verificación dentro del lock
            if _whisper_model_instance is None:
                logger.info(f"ML_SERVICE: Iniciando carga del modelo Whisper ({WHISPER_MODEL_SIZE})...")
                try:
                    # Carga real del modelo
                    # model_dir = os.getenv("WHISPER_MODEL_DIR", None)
                    # _whisper_model_instance = whisper.load_model(WHISPER_MODEL_SIZE, download_root=model_dir)
                    _whisper_model_instance = whisper.load_model(WHISPER_MODEL_SIZE)
                    logger.info(f"ML_SERVICE: Modelo Whisper '{WHISPER_MODEL_SIZE}' cargado exitosamente.")
                except MemoryError as me:
                    logger.error(f"¡MemoryError en ML_SERVICE! No hay suficiente memoria para cargar Whisper '{WHISPER_MODEL_SIZE}'. {me}")
                    _whisper_model_instance = None # Asegurar que quede None si falla
                except Exception as e:
                    logger.error(f"Error crítico durante la carga del modelo Whisper en ML_SERVICE ({WHISPER_MODEL_SIZE}): {e}", exc_info=True)
                    _whisper_model_instance = None # Asegurar que quede None si falla
    return _whisper_model_instance

# --- Evento Startup: YA NO CARGA EL MODELO AQUÍ ---
@app.on_event("startup")
async def startup_event():
    logger.info("Evento startup: Servicio ML iniciado. El modelo Whisper se cargará bajo demanda.")
    # Opcional: Intento de carga inicial no bloqueante (si falla, el servicio igual inicia)
    # try:
    #     get_whisper_model_service()
    # except Exception:
    #     logger.warning("Intento de carga inicial de Whisper fallido, se reintentará bajo demanda.")
    #     pass # No detener el inicio del servicio si falla la carga inicial

# --- Funciones de Utilidad (sin cambios) ---
@sync_to_async
def get_user_name(user_id: str) -> Optional[str]:
    """Obtiene el nombre de usuario desde la base de datos Django."""
    try:
        user_db_id = int(user_id) # Convertir ID a entero
        user = Usuario.objects.get(id=user_db_id)
        name = user.first_name if user.first_name else user.username
        if name:
            logger.debug(f"Nombre de usuario encontrado para ID {user_id}: {name}")
            return name
        else:
            logger.warning(f"Usuario ID {user_id} encontrado, pero sin nombre.")
            return "usuario"
    except Usuario.DoesNotExist:
        logger.warning(f"Usuario con ID {user_id} no encontrado en la base de datos.")
        return None
    except (ValueError, TypeError):
        logger.warning(f"ID de usuario '{user_id}' proporcionado no es un entero válido.")
        return None
    except Exception as e:
        logger.error(f"Error inesperado DB al obtener nombre de usuario para ID {user_id}: {e}", exc_info=True)
        return None

async def generate_audio_edge_tts(text: str, output_path: str, voice: str = DEFAULT_VOICE) -> bool:
    """Genera audio usando Microsoft Edge TTS."""
    if not text or not text.strip():
        logger.error(f"Texto vacío proporcionado a generate_audio_edge_tts para {output_path}")
        return False
    logger.info(f"Generando audio (EdgeTTS) con voz '{voice}' en: {output_path}")
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            logger.error(f"Fallo post-generación EdgeTTS: Archivo no existe o está vacío: {output_path}")
            if os.path.exists(output_path):
                try: os.remove(output_path)
                except OSError: pass
            return False
        logger.info(f"Audio EdgeTTS generado en {output_path} (Tamaño: {os.path.getsize(output_path)} bytes)")
        return True
    except Exception as e:
        logger.error(f"Error durante la generación de audio edge_tts (voz: {voice}, path: {output_path}): {e}", exc_info=True)
        if os.path.exists(output_path):
            try: os.remove(output_path)
            except OSError: pass
        return False

def select_available_model(expected_tokens: int = 200) -> str:
    """Selecciona un modelo Groq disponible basado en límites RPM/TPM."""
    current_time = time.time()
    available_models = []
    logger.debug("Evaluando modelos Groq disponibles...")
    for model_info in GROQ_MODELS:
        model_name = model_info["name"]
        usage = model_usage.setdefault(model_name, {"requests": 0, "tokens": 0, "last_reset": current_time})
        if current_time - usage["last_reset"] >= 60:
            logger.debug(f"Reseteando límites para el modelo Groq: {model_name}")
            usage["requests"], usage["tokens"], usage["last_reset"] = 0, 0, current_time
        can_request = usage["requests"] < model_info["rpm"]
        can_add_tokens = usage["tokens"] + expected_tokens <= model_info["tpm"]
        logger.debug(f"Modelo {model_name}: Req={usage['requests']}/{model_info['rpm']} ({can_request}), Tok={usage['tokens']}+{expected_tokens}/{model_info['tpm']} ({can_add_tokens})")
        if can_request and can_add_tokens:
            available_models.append(model_name)

    if not available_models:
        logger.error("Todos los modelos Groq están actualmente limitados por tasa (RPM/TPM).")
        raise HTTPException(status_code=429, detail="Servicio de IA temporalmente sobrecargado. Intenta de nuevo en un momento.")

    selected = random.choice(available_models)
    logger.info(f"Modelo Groq seleccionado para la solicitud: {selected}")
    model_usage[selected]["requests"] += 1
    model_usage[selected]["tokens"] += expected_tokens
    logger.debug(f"Uso actualizado para {selected}: Req={model_usage[selected]['requests']}, Tok={model_usage[selected]['tokens']}")
    return selected

async def get_groq_response(
    user_id: str, user_input: str, user_name: str, system_prompt: str,
    history_dict: Dict[str, List[Dict[str, str]]], max_history: int,
    model: str = None, max_tokens: int = 150
) -> str:
    """Obtiene una respuesta conversacional de la API de Groq."""
    if user_id not in history_dict: history_dict[user_id] = []
    user_history = history_dict[user_id]
    user_history.append({"role": "user", "content": user_input})
    if len(user_history) > max_history * 2:
        logger.debug(f"Historial para user {user_id} truncado de {len(user_history)//2} a {max_history} turnos.")
        user_history = user_history[-(max_history * 2):]
        history_dict[user_id] = user_history
    messages = [{"role": "system", "content": system_prompt}] + user_history
    logger.info(f"Llamando a Groq para user {user_id}. Historial actual: {len(user_history)//2 + (len(user_history)%2)} turnos.")
    try:
        if model is None: model = select_available_model(expected_tokens=max_tokens)
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        data = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7}
        response = await asyncio.to_thread(requests.post, GROQ_API_URL, headers=headers, json=data, timeout=45)
        response.raise_for_status()
        response_data = response.json()
        assistant_message = response_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not assistant_message:
            logger.error(f"Respuesta de Groq vacía para user {user_id} (modelo: {model}).")
            assistant_message = "Lo siento, no pude generar una respuesta en este momento."
        else:
            user_history.append({"role": "assistant", "content": assistant_message})
            logger.info(f"Respuesta de Groq recibida para user {user_id} (modelo: {model}).")
        return assistant_message
    except requests.exceptions.Timeout:
        logger.error(f"Timeout (>45s) esperando respuesta de Groq API para user {user_id}.")
        return "Lo siento, la conexión con el servicio de IA tardó demasiado."
    except requests.exceptions.RequestException as e:
        status_code = e.response.status_code if hasattr(e, 'response') and e.response is not None else 503
        logger.error(f"Error en llamada a Groq API (Status: {status_code}) para user {user_id}: {e}", exc_info=True)
        if status_code == 401: return "Error de autenticación con el servicio de IA. Verifica la API Key."
        elif status_code == 429: return "El servicio de IA está sobrecargado actualmente. Por favor, inténtalo de nuevo más tarde."
        elif status_code >= 500: return "El servicio de IA está experimentando problemas técnicos. Intenta más tarde."
        else: return "Hubo un problema conectando con el servicio de IA."
    except HTTPException as http_rate_limit:
        if http_rate_limit.status_code == 429:
             logger.warning(f"Rate limit alcanzado ANTES de llamar a Groq para user {user_id}.")
             return http_rate_limit.detail
        else:
             logger.error(f"HTTPException inesperada durante get_groq_response para user {user_id}: {http_rate_limit}", exc_info=True)
             raise http_rate_limit
    except Exception as e:
        logger.error(f"Error inesperado procesando respuesta de Groq para user {user_id}: {e}", exc_info=True)
        return "Lo siento, ocurrió un error inesperado al procesar tu solicitud."


# --- Endpoint Meditación Conversacional (OPTIMIZADO) ---
@app.post("/meditation-step")
async def meditation_step(
    user_id: str = Form(...), theme: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None), audio: Optional[UploadFile] = File(None)
):
    temp_audio_path = None
    response_audio_path = None
    current_session_id = session_id
    is_finished = False
    user_input_text = None # Inicializar

    try:
        # --- Lógica de Inicio/Continuación de Sesión (sin cambios en la lógica, solo formato) ---
        session_user_name = "usuario"
        current_step = 0
        if not current_session_id and theme:
            user_name_from_db = await get_user_name(user_id) or "participante"
            current_session_id = str(uuid.uuid4())
            logger.info(f"Iniciando sesión meditación ({current_session_id}) para user {user_id} ({user_name_from_db}) sobre '{theme}'")
            meditation_sessions[current_session_id] = {"theme": theme, "history": [], "step": 0, "user_name": user_name_from_db}
            user_input_text = f"Iniciar meditación sobre {theme}" # Texto inicial para Groq
            current_step = 1
            session_user_name = user_name_from_db
        elif current_session_id:
            if current_session_id not in meditation_sessions:
                raise HTTPException(status_code=404, detail="Sesión meditación no encontrada.")
            session_data = meditation_sessions[current_session_id]
            session_user_name = session_data["user_name"]
            current_step = session_data["step"] + 1
            logger.info(f"Continuando sesión meditación {current_session_id} (Paso {current_step}) para '{session_user_name}'")
            if audio:
                # --- Transcripción si hay audio ---
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
                    temp_audio_path = tmp_file.name
                    try: shutil.copyfileobj(audio.file, tmp_file)
                    finally: await audio.close()

                # --- Obtener Modelo Whisper (Lazy Load) ---
                local_whisper_model = get_whisper_model_service()
                if not local_whisper_model:
                     logger.error(f"Meditación: Modelo Whisper no disponible al procesar para user {user_id}, session {current_session_id}")
                     raise HTTPException(status_code=503, detail="Servicio de transcripción no disponible.")
                # ------------------------------------------

                try:
                    logger.info(f"Meditación: Iniciando transcripción Whisper para {temp_audio_path} (User: {user_id}, Session: {current_session_id})")
                    transcript_result = await asyncio.to_thread(local_whisper_model.transcribe, temp_audio_path, language="es")
                    user_input_text = transcript_result["text"].strip() or "[Silencio]" # Usar default si está vacío
                    logger.info(f"Meditación: Texto transcrito (User: {user_id}, Session: {current_session_id}): '{user_input_text[:100]}...'")
                except Exception as e_whisper_med:
                     logger.exception(f"!!! ERROR DURANTE TRANSCRIPCIÓN WHISPER en /meditation-step (User: {user_id}, Session: {current_session_id}) !!!")
                     raise HTTPException(status_code=500, detail="Error interno al procesar la voz.")
            else:
                user_input_text = "listo" # Asumir 'listo' si no se envía audio
        else:
            raise HTTPException(status_code=400, detail="Se requiere 'theme' para iniciar o 'session_id' para continuar.")

        # --- Lógica de Meditación (Groq + TTS) ---
        if user_input_text is None: # Seguridad por si no se asignó por alguna razón
             raise HTTPException(status_code=500, detail="Error interno: No se pudo determinar la entrada del usuario.")

        session_data = meditation_sessions[current_session_id]
        session_data["history"].append({"role": "user", "content": user_input_text})
        assistant_response_text, is_finished = await get_groq_meditation_step(
            session_history=session_data["history"], theme=session_data["theme"],
            user_name=session_user_name, current_step=current_step
        )
        session_data["step"] = current_step
        session_data["history"].append({"role": "assistant", "content": assistant_response_text})

        # --- Generación de Audio de Respuesta ---
        response_audio_filename = f"meditation_{current_session_id}_step{current_step}.mp3"
        response_audio_path = os.path.join(tempfile.gettempdir(), response_audio_filename)
        logger.info(f"Meditación: Generando audio respuesta para user {user_id}, session {current_session_id}, step {current_step}")
        success = await generate_audio_edge_tts(assistant_response_text, response_audio_path)
        if not success:
            logger.error(f"Meditación: Fallo al generar audio respuesta para user {user_id}, session {current_session_id}")
            # Devolver texto como fallback si falla el audio
            return JSONResponse(
                content={
                    "response_text": assistant_response_text,
                    "error": "Fallo al generar audio de respuesta.",
                    "X-Meditation-Session-Id": str(current_session_id),
                    "X-Meditation-Finished": str(is_finished).lower()
                },
                status_code=200 # Éxito parcial
            )

        # --- Preparar y Enviar Respuesta de Audio ---
        headers = {
            "X-Meditation-Session-Id": str(current_session_id),
            "X-Meditation-Finished": str(is_finished).lower()
        }
        response_filename_user = f"meditation_step_{current_step}.mp3"

        if is_finished:
            logger.info(f"Meditación {current_session_id} finalizada. Eliminando datos de sesión.")
            meditation_sessions.pop(current_session_id, None)
            response_filename_user = "meditation_final_step.mp3"

        logger.info(f"Meditación: Enviando respuesta de audio para user {user_id}, session {current_session_id}")
        # Considerar BackgroundTasks para limpiar response_audio_path
        return FileResponse(
            response_audio_path,
            media_type="audio/mpeg",
            filename=response_filename_user,
            headers=headers
        )

    except HTTPException as http_exc:
        logger.warning(f"HTTPException manejada en /meditation-step (User: {user_id}, Session: {current_session_id}): {http_exc.status_code} - {http_exc.detail}")
        raise http_exc
    except Exception as e:
        logger.exception(f"!!! ERROR INESPERADO GENÉRICO en /meditation-step (User: {user_id}, Session: {current_session_id}) !!!")
        return JSONResponse(content={"error": "Error interno inesperado durante la meditación."}, status_code=500)
    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
                logger.debug(f"Archivo temporal de entrada meditación eliminado: {temp_audio_path}")
            except Exception as e_clean:
                logger.warning(f"No se pudo eliminar archivo temporal meditación {temp_audio_path}: {e_clean}")


# --- Endpoint Asistente General (OPTIMIZADO) ---
@app.post("/assistant")
async def assistant(audio: UploadFile = File(...), user_id: str = Form(...)):
    temp_audio_path = None
    response_audio_path = None
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id obligatorio.")
    try:
        # --- Guardar Audio ---
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            temp_audio_path = tmp_file.name
            logger.info(f"Guardando audio de entrada para user {user_id} en: {temp_audio_path}")
            try: shutil.copyfileobj(audio.file, tmp_file)
            finally: await audio.close()
        logger.info(f"Audio entrada /assistant guardado: {temp_audio_path} (User: {user_id})")

        # --- OBTENER MODELO WHISPER (Lazy Load) ---
        local_whisper_model = get_whisper_model_service()
        if not local_whisper_model:
            logger.error(f"Error crítico: Modelo Whisper no disponible al procesar /assistant para user {user_id}.")
            raise HTTPException(status_code=503, detail="Servicio de transcripción no disponible temporalmente.")
        # -----------------------------------------

        # --- Transcripción Whisper ---
        transcript_text = ""
        try:
            logger.info(f"Iniciando transcripción Whisper para: {temp_audio_path} (User: {user_id})")
            # --- USAR LA INSTANCIA OBTENIDA ---
            transcript_result = await asyncio.to_thread(local_whisper_model.transcribe, temp_audio_path, language="es")
            # ----------------------------------
            logger.info(f"Transcripción Whisper completada para user {user_id}.")
            transcript_text = transcript_result.get("text", "").strip()
            if transcript_text: logger.info(f"Texto transcrito (User: {user_id}): '{transcript_text[:100]}...'")
            else: logger.info(f"Transcripción resultó en texto vacío (User: {user_id}).")
        except Exception as e_whisper:
            logger.exception(f"!!! ERROR DURANTE LA TRANSCRIPCIÓN WHISPER en /assistant (User: {user_id}) !!!")
            raise HTTPException(status_code=500, detail="Error interno al procesar la voz.")

        # --- Manejo de Silencio o Texto Vacío ---
        if not transcript_text:
            logger.warning(f"No se detectó habla o transcripción vacía para user {user_id}.")
            no_speech_text = "Lo siento, no te he entendido. ¿Puedes repetirlo?"
            response_audio_path = os.path.join(tempfile.gettempdir(), f"no_speech_{uuid.uuid4()}.mp3")
            logger.info(f"Generando audio de 'no habla' para user {user_id} en {response_audio_path}")
            success = await generate_audio_edge_tts(no_speech_text, response_audio_path)
            if success:
                 logger.info(f"Enviando respuesta de 'no habla' a user {user_id}")
                 # Considerar BackgroundTasks para limpiar este archivo
                 return FileResponse(response_audio_path, media_type="audio/mpeg", filename="error_no_speech.mp3")
            else:
                 logger.error(f"Fallo al generar audio de 'no habla' para user {user_id}.")
                 return JSONResponse(content={"error": "No se pudo procesar el audio, y falló la generación de respuesta."}, status_code=500)

        # --- Obtener Nombre de Usuario ---
        user_name = await get_user_name(user_id) or "usuario"

        # --- Llamada a Groq ---
        system_prompt = (
            f"Eres Senti, un asistente de IA conversacional, útil y amigable. "
            f"Estás hablando con '{user_name}'. Responde de forma clara y concisa. "
            f"Mantén un tono amable y servicial. No eres un guía de meditación en este rol."
        )
        assistant_response_text = await get_groq_response(
            user_id=user_id, user_input=transcript_text, user_name=user_name,
            system_prompt=system_prompt, history_dict=chat_history,
            max_history=MAX_CHAT_HISTORY_TURNS, max_tokens=250
        )

        # --- Generar Audio de Respuesta ---
        response_audio_filename = f"assistant_response_{user_id}_{uuid.uuid4()}.mp3"
        response_audio_path = os.path.join(tempfile.gettempdir(), response_audio_filename)
        logger.info(f"Generando audio de respuesta asistente para user {user_id} en: {response_audio_path}")
        success = await generate_audio_edge_tts(assistant_response_text, response_audio_path)

        if not success:
            logger.error(f"Fallo al generar audio de respuesta asistente (user {user_id}). Texto era: '{assistant_response_text[:100]}...'")
            return JSONResponse(
                content={"response_text": assistant_response_text, "error": "Fallo al generar audio de respuesta."},
                status_code=200 # Éxito parcial
             )

        # --- Enviar Respuesta de Audio ---
        logger.info(f"Enviando respuesta de audio /assistant para user {user_id}: {response_audio_path}")
        # Considerar BackgroundTasks para limpiar este archivo
        return FileResponse(response_audio_path, media_type="audio/mpeg", filename="assistant_response.mp3")

    except HTTPException as http_exc:
        logger.warning(f"HTTPException manejada en /assistant (User: {user_id}): {http_exc.status_code} - {http_exc.detail}")
        raise http_exc
    except Exception as e:
        logger.exception(f"!!! ERROR INESPERADO GENÉRICO en /assistant (User: {user_id}) !!!")
        return JSONResponse(content={"error": "Error interno inesperado en el asistente."}, status_code=500)
    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
                logger.debug(f"Archivo temporal de entrada eliminado: {temp_audio_path}")
            except Exception as e_clean:
                logger.warning(f"No se pudo eliminar archivo temporal {temp_audio_path}: {e_clean}")


# --- Función auxiliar get_groq_meditation_step (sin cambios) ---
async def get_groq_meditation_step(
    session_history: List[Dict[str, str]], theme: str, user_name: str,
    current_step: int, model: str = None, max_tokens: int = 150
) -> Tuple[Optional[str], bool]:
    is_finished = False
    if current_step > MAX_MEDITATION_STEPS:
        logger.info(f"Meditación: Límite de pasos ({MAX_MEDITATION_STEPS}) alcanzado.")
        is_finished = True
        assistant_message = f"Muy bien, {user_name}. Hemos llegado al final de nuestra práctica sobre '{theme}'. Tómate un momento para notar cómo te sientes. Cuando estés listo/a, puedes abrir los ojos. Que la calma te acompañe."
        return assistant_message, is_finished
    system_prompt = (
        f"Eres Senti, guía de meditación calmada y paciente. Guías a '{user_name}' en meditación sobre '{theme}'. "
        f"Da UNA instrucción o pregunta CORTA por turno. Espera respuesta ('listo', silencio, etc.). Tono tranquilo y amable. "
        f"Pasos generales: Saludo/listo -> Postura/ojos -> Respiración (2-3 turnos) -> Foco en '{theme}' (varios turnos) -> Vuelta al presente -> Indicación de finalización (sin despedida final aquí). "
        f"**IMPORTANTE: SOLO tu próxima frase/pregunta. Sé MUY concisa.**"
    )
    messages = [{"role": "system", "content": system_prompt}] + session_history
    try:
        if model is None: model = select_available_model(expected_tokens=max_tokens)
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        data = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.5}
        response = await asyncio.to_thread(requests.post, GROQ_API_URL, headers=headers, json=data, timeout=45)
        response.raise_for_status()
        response_data = response.json()
        assistant_message = response_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not assistant_message:
             logger.error(f"Respuesta Groq vacía meditación step {current_step}.")
             assistant_message = "Continuemos con calma. Concéntrate en tu respiración."
        else:
             logger.info(f"Groq meditation response (step {current_step}): '{assistant_message[:100]}...'")
        return assistant_message, False
    except requests.exceptions.Timeout:
        logger.error(f"Timeout (>45s) en llamada Groq para meditación step {current_step}, user {user_name}")
        return f"Lo siento {user_name}, la conexión está un poco lenta. Tomemos una respiración profunda.", False
    except requests.exceptions.RequestException as e:
        status_code = e.response.status_code if hasattr(e, 'response') and e.response is not None else 503
        logger.error(f"Error ({status_code}) en llamada Groq para meditación step {current_step}, user {user_name}: {e}", exc_info=True)
        return f"Lo siento {user_name}, hubo un problema técnico con la IA.", False
    except HTTPException as http_rate_limit:
        if http_rate_limit.status_code == 429:
             logger.warning(f"Rate limit alcanzado ANTES de llamar a Groq para meditación step {current_step}, user {user_name}")
             return http_rate_limit.detail, False
        else:
             logger.error(f"HTTPException inesperada durante get_groq_meditation_step para user {user_name}: {http_rate_limit}", exc_info=True)
             raise http_rate_limit
    except Exception as e:
        logger.error(f"Error inesperado en get_groq_meditation_step {current_step}, user {user_name}: {e}", exc_info=True)
        return f"Disculpa {user_name}, ocurrió algo inesperado. Mantén la calma.", False

# --- Uvicorn runner (sin cambios) ---
if __name__ == "__main__":
    import uvicorn
    print("--- EJECUTANDO DIRECTAMENTE (NO DESDE SYSTEMD) ---")
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    logger.info("Iniciando servidor FastAPI para desarrollo local...")
    port = int(os.getenv("PORT", 8001))
    host = "127.0.0.1"
    logger.info(f"Servidor corriendo en http://{host}:{port}")
    uvicorn.run("ml_service:app", host=host, port=port, reload=True)
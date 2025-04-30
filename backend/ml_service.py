# backend/ml_service.py
import os
import pathlib
from dotenv import load_dotenv
import django
import tempfile
from typing import List, Dict, Optional, Tuple
import logging
# QUITAR BackgroundTask de los imports
from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
# QUITAR BackgroundTask de los imports (si estaba aquí también)
from asgiref.sync import sync_to_async
import edge_tts
import asyncio
import shutil
import uuid
import requests
import whisper
import random
import time

# --- Cargar .env desde el directorio padre ---
current_script_dir = pathlib.Path(__file__).parent
dotenv_path = current_script_dir.parent / '.env'
if dotenv_path.is_file():
    print(f"INFO: Cargando variables de entorno desde: {dotenv_path}")
    load_dotenv(dotenv_path=dotenv_path)
else:
    print(f"WARNING: No se encontró el archivo .env en {dotenv_path}.")

# --- Configuración de Django ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
try:
    django.setup()
    from api.models import Usuario
    logger = logging.getLogger(__name__)
    logger.info("Configuración de Django completada y modelos importados.")
except Exception as e:
    print(f"ERROR CRÍTICO durante django.setup(): {e}")
    print("Verifica tu archivo settings.py y las variables de entorno requeridas.")
    import sys
    sys.exit("Fallo al iniciar Django. Saliendo.")

# --- Configuración de FastAPI ---
app = FastAPI()
origins = [
    "http://localhost:5174",
    "http://localhost:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Meditation-Session-Id", "X-Meditation-Finished"]
)

# --- Configuración de APIs y Modelos ---
WHISPER_MODEL_SIZE = "base"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY no encontrada en el entorno. Las llamadas a Groq fallarán.")

# --- Modelos Groq ---
GROQ_MODELS = [
    {"name": "llama-3.1-8b-instant", "rpm": 30, "tpm": 14400},
    {"name": "llama3-8b-8192", "rpm": 30, "tpm": 6000},
]
model_usage = {model["name"]: {"requests": 0, "tokens": 0, "last_reset": time.time()} for model in GROQ_MODELS}

# --- Estado Global (Memoria) ---
meditation_sessions: Dict[str, Dict] = {}
chat_history: Dict[str, List[Dict[str, str]]] = {}
whisper_model = None

# --- Constantes ---
MAX_MEDITATION_STEPS = 8
DEFAULT_VOICE = "es-ES-AlvaroNeural"
MAX_CHAT_HISTORY_TURNS = 10

# --- Evento Startup ---
@app.on_event("startup")
async def startup_event():
    global whisper_model
    logger.info(f"Cargando modelo Whisper ({WHISPER_MODEL_SIZE})...")
    try:
        whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
        logger.info("Modelo Whisper cargado.")
    except Exception as e:
        logger.error(f"Error cargando modelo Whisper: {e}", exc_info=True)

# --- Funciones de Utilidad ---
@sync_to_async
def get_user_name(user_id: str) -> Optional[str]:
    try:
        user_db_id = int(user_id)
        user = Usuario.objects.get(id=user_db_id)
        name = user.first_name if user.first_name else user.username
        if name:
            logger.debug(f"Nombre de usuario encontrado para ID {user_id}: {name}")
            return name
        else:
            logger.debug(f"Usuario ID {user_id} encontrado, pero sin nombre.")
            return None
    except Usuario.DoesNotExist:
        logger.warning(f"Usuario con ID {user_id} no encontrado.")
        return None
    except (ValueError, TypeError):
        logger.warning(f"ID de usuario '{user_id}' no es un entero válido.")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al obtener nombre de usuario para ID {user_id}: {e}", exc_info=True)
        return None

async def generate_audio_edge_tts(text: str, output_path: str, voice: str = DEFAULT_VOICE) -> bool:
    if not text or not text.strip():
        logger.error("Texto vacío para generate_audio_edge_tts")
        return False
    logger.info(f"Generando audio (EdgeTTS) con voz '{voice}' en: {output_path}")
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            logger.error(f"Fallo al generar audio EdgeTTS o archivo vacío: {output_path}")
            return False
        logger.info(f"Audio generado en {output_path} (Tamaño: {os.path.getsize(output_path)} bytes)")
        return True
    except Exception as e:
        logger.error(f"Error durante la generación de audio edge_tts (voz: {voice}): {e}", exc_info=True)
        return False

def select_available_model(expected_tokens: int = 200) -> str:
    current_time = time.time()
    available_models = []
    logger.debug("Seleccionando modelo Groq...")
    for model_info in GROQ_MODELS:
        model_name = model_info["name"]
        usage = model_usage.setdefault(model_name, {"requests": 0, "tokens": 0, "last_reset": current_time})
        if current_time - usage["last_reset"] >= 60:
            usage["requests"], usage["tokens"], usage["last_reset"] = 0, 0, current_time
        can_request = usage["requests"] < model_info["rpm"]
        can_add_tokens = usage["tokens"] + expected_tokens <= model_info["tpm"]
        if can_request and can_add_tokens: available_models.append(model_name)
    if not available_models:
        raise HTTPException(status_code=429, detail="Servicio temporalmente sobrecargado.")
    selected = random.choice(available_models)
    logger.info(f"Modelo Groq seleccionado: {selected}")
    model_usage[selected]["requests"] += 1
    model_usage[selected]["tokens"] += expected_tokens
    return selected

async def get_groq_response(
    user_id: str, user_input: str, user_name: str, system_prompt: str,
    history_dict: Dict[str, List[Dict[str, str]]], max_history: int,
    model: str = None, max_tokens: int = 150
) -> str:
    if user_id not in history_dict: history_dict[user_id] = []
    user_history = history_dict[user_id]
    user_history.append({"role": "user", "content": user_input})
    if len(user_history) > max_history * 2:
        user_history = user_history[-(max_history * 2):]
        history_dict[user_id] = user_history
    messages = [{"role": "system", "content": system_prompt}] + user_history
    logger.info(f"Llamando a Groq para user {user_id}. Historial: {len(user_history)} mensajes.")
    try:
        if model is None: model = select_available_model(expected_tokens=max_tokens)
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        data = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7}
        response = await asyncio.to_thread(
            requests.post, GROQ_API_URL, headers=headers, json=data, timeout=45
        )
        response.raise_for_status()
        response_data = response.json()
        assistant_message = response_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not assistant_message:
            logger.error("Respuesta de Groq vacía.")
            assistant_message = "Lo siento, no pude procesar eso."
        else:
            user_history.append({"role": "assistant", "content": assistant_message})
            logger.info(f"Respuesta de Groq recibida para user {user_id}.")
        return assistant_message
    except requests.exceptions.Timeout:
        logger.error("Timeout con Groq API.")
        return "Lo siento, la conexión tardó demasiado."
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en llamada a Groq API: {e}", exc_info=True)
        status_code = e.response.status_code if hasattr(e, 'response') and e.response is not None else 500
        if status_code == 401: return "Error de autenticación con IA."
        elif status_code == 429: return "Servicio de IA sobrecargado."
        return "Problema conectando con IA."
    except Exception as e:
        logger.error(f"Error inesperado procesando respuesta de Groq: {e}", exc_info=True)
        return "Error inesperado al procesar tu solicitud."

# --- Endpoint Meditación Conversacional (SIN BackgroundTask) ---
@app.post("/meditation-step")
async def meditation_step(
    user_id: str = Form(...), theme: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None), audio: Optional[UploadFile] = File(None)
):
    temp_audio_path = None
    response_audio_path = None
    current_session_id = session_id
    is_finished = False
    try:
        session_user_name = "usuario"
        current_step = 0
        if not current_session_id and theme:
            user_name_from_db = await get_user_name(user_id) or "participante"
            current_session_id = str(uuid.uuid4())
            logger.info(f"Iniciando sesión meditación ({current_session_id}) para user {user_id} ({user_name_from_db}) sobre '{theme}'")
            meditation_sessions[current_session_id] = {"theme": theme, "history": [], "step": 0, "user_name": user_name_from_db}
            user_input_text = f"Iniciar meditación sobre {theme}"
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
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
                    temp_audio_path = tmp_file.name
                    try: shutil.copyfileobj(audio.file, tmp_file)
                    finally: await audio.close()
                if not whisper_model: raise HTTPException(status_code=503, detail="Transcripción no disponible.")
                try:
                    transcript_result = await asyncio.to_thread(whisper_model.transcribe, temp_audio_path, language="es")
                    user_input_text = transcript_result["text"].strip() or "[Silencio]"
                    logger.info(f"Texto transcrito: '{user_input_text}'")
                except Exception as e: raise HTTPException(status_code=500, detail="Error al procesar audio.")
            else:
                user_input_text = "listo"
        else:
            raise HTTPException(status_code=400, detail="Se requiere 'theme' o 'session_id'.")

        session_data = meditation_sessions[current_session_id]
        session_data["history"].append({"role": "user", "content": user_input_text})
        assistant_response_text, is_finished = await get_groq_meditation_step(
            session_history=session_data["history"], theme=session_data["theme"],
            user_name=session_user_name, current_step=current_step
        )
        session_data["step"] = current_step
        session_data["history"].append({"role": "assistant", "content": assistant_response_text})

        response_audio_filename = f"meditation_{current_session_id}_step{current_step}.mp3"
        response_audio_path = os.path.join(tempfile.gettempdir(), response_audio_filename)
        success = await generate_audio_edge_tts(assistant_response_text, response_audio_path)
        if not success: raise HTTPException(status_code=500, detail="Error al generar audio meditación.")

        headers = {"X-Meditation-Session-Id": str(current_session_id), "X-Meditation-Finished": str(is_finished).lower()}
        response_filename = f"meditation_step_{current_step}.mp3"
        if is_finished:
            logger.info(f"Meditación {current_session_id} finalizada. Eliminando sesión.")
            meditation_sessions.pop(current_session_id, None)
            response_filename = "meditation_final_step.mp3"

        # Devolver FileResponse SIN BackgroundTask
        return FileResponse(
            response_audio_path,
            media_type="audio/mpeg",
            filename=response_filename,
            headers=headers
            # SIN background task aquí
        )
    except HTTPException as http_exc: raise http_exc
    except Exception as e:
        logger.error(f"Error inesperado en /meditation-step: {e}", exc_info=True)
        return JSONResponse(content={"error": "Error interno meditación."}, status_code=500)
    finally:
        # Limpieza manual del audio de entrada si existe
        if temp_audio_path and os.path.exists(temp_audio_path):
            try: os.remove(temp_audio_path)
            except Exception as e_clean: logger.warning(f"No se pudo eliminar {temp_audio_path}: {e_clean}")
        # El audio de SALIDA NO se limpia automáticamente aquí
        # Se acumularán archivos en temp hasta el próximo reinicio del servidor o limpieza manual.

# --- Endpoint Asistente General (SIN BackgroundTask) ---
@app.post("/assistant")
async def assistant(audio: UploadFile = File(...), user_id: str = Form(...)):
    temp_audio_path = None
    response_audio_path = None
    if not user_id: raise HTTPException(status_code=422, detail="user_id obligatorio.")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            temp_audio_path = tmp_file.name
            try: shutil.copyfileobj(audio.file, tmp_file)
            finally: await audio.close()
        logger.info(f"Audio entrada /assistant: {temp_audio_path}")

        if not whisper_model: raise HTTPException(status_code=503, detail="Transcripción no disponible.")
        try:
            transcript_result = await asyncio.to_thread(whisper_model.transcribe, temp_audio_path, language="es")
            transcript_text = transcript_result["text"].strip()
            logger.info(f"Texto transcrito user {user_id}: '{transcript_text}'")
        except Exception as e: raise HTTPException(status_code=500, detail="Error procesando voz.")

        if not transcript_text:
            logger.warning(f"No se detectó habla user {user_id}.")
            no_speech_text = "Lo siento, no te he entendido. ¿Puedes repetirlo?"
            response_audio_path = os.path.join(tempfile.gettempdir(), f"no_speech_{uuid.uuid4()}.mp3")
            success = await generate_audio_edge_tts(no_speech_text, response_audio_path)
            if success:
                # Devolver SIN BackgroundTask
                 return FileResponse(
                     response_audio_path, media_type="audio/mpeg", filename="error_no_speech.mp3"
                 )
            else:
                 return JSONResponse(content={"error": "No se detectó habla y falló audio."}, status_code=400)

        user_name = await get_user_name(user_id) or "usuario"
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

        response_audio_filename = f"assistant_response_{uuid.uuid4()}.mp3"
        response_audio_path = os.path.join(tempfile.gettempdir(), response_audio_filename)
        success = await generate_audio_edge_tts(assistant_response_text, response_audio_path)
        if not success:
            logger.error(f"Fallo al generar audio asistente (user {user_id}).")
            return JSONResponse(
                content={"response_text": assistant_response_text, "error": "Fallo al generar audio."},
                status_code=200
             )

        logger.info(f"Respuesta audio /assistant: {response_audio_path}")
        # Devolver SIN BackgroundTask
        return FileResponse(
            response_audio_path, media_type="audio/mpeg", filename="assistant_response.mp3"
        )

    except HTTPException as http_exc: raise http_exc
    except Exception as e:
        logger.error(f"Error inesperado en /assistant user {user_id}: {e}", exc_info=True)
        return JSONResponse(content={"error": "Error interno inesperado asistente."}, status_code=500)
    finally:
        # Limpieza manual del audio de entrada si existe
        if temp_audio_path and os.path.exists(temp_audio_path):
            try: os.remove(temp_audio_path)
            except Exception as e_clean: logger.warning(f"No se pudo eliminar {temp_audio_path}: {e_clean}")
        # El audio de SALIDA NO se limpia automáticamente aquí

# --- Función auxiliar para la lógica de meditación (SIN CAMBIOS EN SU LÓGICA INTERNA) ---
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
        response = await asyncio.to_thread(
            requests.post, GROQ_API_URL, headers=headers, json=data, timeout=45
        )
        response.raise_for_status()
        response_data = response.json()
        assistant_message = response_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not assistant_message:
             logger.error(f"Respuesta Groq vacía meditación step {current_step}.")
             assistant_message = "Continuemos con calma. Concéntrate en tu respiración." # Fallback simple
        else:
             logger.info(f"Groq meditation response (step {current_step}): '{assistant_message[:100]}...'")
        return assistant_message, False # is_finished se decide arriba por contador
    except requests.exceptions.Timeout: return f"Lo siento {user_name}, hay un retraso. Tomemos una pausa.", False
    except requests.exceptions.RequestException as e: return f"Lo siento {user_name}, hubo un problema técnico.", False
    except Exception as e: return f"Disculpa {user_name}, ocurrió algo inesperado.", False

# --- Uvicorn runner ---
if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("Iniciando servidor FastAPI directamente...")
    port = int(os.getenv("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
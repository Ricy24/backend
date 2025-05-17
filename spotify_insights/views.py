# spotify_insights/views.py
import requests
import base64
from datetime import timedelta
# import datetime as dt # No se usa directamente, timedelta es suficiente
import secrets
import statistics
from collections import Counter

from django.shortcuts import redirect
from django.conf import settings
from django.utils import timezone
from django.http import HttpResponseBadRequest
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from api.models import Usuario # Asegúrate que esta importación sea correcta
from .models import SpotifyToken

from groq import Groq

# --- Constantes y Configuración ---
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE_URL = "https://api.spotify.com/v1/"
SCOPES = "user-top-read user-read-recently-played user-read-email user-library-read user-follow-read"

# LISTA DE HERRAMIENTAS DE SENTI
SENTI_TOOLS_LIST = [
    "Diario Emocional Guiado", "Meditaciones para la Ansiedad",
    "Ejercicios de Respiración Profunda", "Reto de Gratitud de 7 Días",
    "Visualizaciones para la Calma", "Sonidos Relajantes de la Naturaleza",
    "Técnicas de Mindfulness para el Estrés"
]

# --- Vistas de Autenticación OAuth2 con Spotify ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_spotify_oauth_state(request):
    state = secrets.token_urlsafe(16)
    # print(f"AUTH: Generado state para OAuth: {state}") # Log opcional
    return Response({'state': state}, status=status.HTTP_200_OK)

def spotify_redirect_to_provider(request):
    state_from_frontend = request.GET.get('state')
    if not state_from_frontend:
        return HttpResponseBadRequest("Falta el parámetro 'state'.")
    # print(f"AUTH: Redirigiendo a Spotify con state: {state_from_frontend}") # Log opcional
    auth_params = {
        'client_id': settings.SPOTIFY_CLIENT_ID, 'response_type': 'code',
        'redirect_uri': settings.SPOTIFY_REDIRECT_URI, 'scope': SCOPES,
        'state': state_from_frontend, 'show_dialog': 'true',
    }
    auth_url = f"{SPOTIFY_AUTH_URL}?{'&'.join([f'{k}={v}' for k, v in auth_params.items()])}"
    return redirect(auth_url)

def spotify_callback_handler(request):
    code = request.GET.get('code')
    state_received = request.GET.get('state')
    error = request.GET.get('error')
    frontend_loading_page_path = "/dashboard/spotify-wrapped/loading" # Asegúrate que esta ruta sea correcta

    # print(f"CALLBACK: Recibido de Spotify - code: {'present' if code else 'missing'}, state: {state_received}, error: {error}") # Log opcional

    if error:
        frontend_error_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?error_from_spotify={error}&state={state_received or ''}"
        return redirect(frontend_error_url)
    if not code or not state_received:
        return HttpResponseBadRequest("Respuesta inválida: faltan 'code' o 'state'.")

    auth_string = f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}"
    auth_base64 = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    headers = {'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/x-www-form-urlencoded'}
    payload = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': settings.SPOTIFY_REDIRECT_URI}

    try:
        # print("CALLBACK: Solicitando token a Spotify...") # Log opcional
        response = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=payload, timeout=10)
        # print(f"CALLBACK: Respuesta de Spotify para token - Status: {response.status_code}") # Log opcional
        response.raise_for_status()
        token_info = response.json()
        # print(f"CALLBACK: Token info recibido: scopes='{token_info.get('scope')}'") # Log opcional
    except requests.exceptions.RequestException as e:
        # print(f"CALLBACK: Error solicitando token a Spotify: {e}") # Log opcional
        frontend_error_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?error_type=token_exchange&state={state_received}"
        return redirect(frontend_error_url)

    access_token = token_info.get('access_token')
    refresh_token = token_info.get('refresh_token')
    expires_in_seconds = token_info.get('expires_in')

    if not access_token or not expires_in_seconds:
        # print("CALLBACK: Respuesta de token inválida de Spotify (sin access_token o expires_in)") # Log opcional
        frontend_error_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?error_type=invalid_token_response&state={state_received}"
        return redirect(frontend_error_url)

    try:
        # print(f"CALLBACK: Guardando token temporal con state: {state_received}") # Log opcional
        SpotifyToken.objects.filter(oauth_state_key=state_received).delete() # Eliminar si ya existe uno con el mismo state
        SpotifyToken.objects.create(
            user=None, oauth_state_key=state_received, access_token=access_token,
            refresh_token=refresh_token, expires_in=timezone.now() + timedelta(seconds=expires_in_seconds),
            token_type=token_info.get('token_type', 'Bearer'), scope=token_info.get('scope')
        )
        # print("CALLBACK: Token temporal guardado.") # Log opcional
    except Exception as e:
        # print(f"CALLBACK: Error guardando token temporal en BD: {e}") # Log opcional
        frontend_error_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?error_type=db_save_temp_token&state={state_received}"
        return redirect(frontend_error_url)
    
    frontend_success_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?state={state_received}&code_received=true"
    return redirect(frontend_success_url)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def associate_spotify_token(request):
    state_from_frontend = request.data.get('state')
    # print(f"ASSOCIATE_TOKEN: Recibido state: {state_from_frontend} para usuario {request.user.email}") # Log opcional
    if not state_from_frontend:
        return Response({'error': "Falta 'state'."}, status=status.HTTP_400_BAD_REQUEST)
    
    senti_user = request.user
    try:
        token_to_associate = SpotifyToken.objects.get(oauth_state_key=state_from_frontend, user__isnull=True)
        # print(f"ASSOCIATE_TOKEN: Token temporal encontrado para state {state_from_frontend}.") # Log opcional
        SpotifyToken.objects.filter(user=senti_user).exclude(pk=token_to_associate.pk).delete() # Eliminar tokens antiguos del mismo usuario
        token_to_associate.user = senti_user
        token_to_associate.oauth_state_key = None # Limpiar el state una vez asociado
        token_to_associate.save()
        # print(f"ASSOCIATE_TOKEN: Token asociado exitosamente al usuario {senti_user.email}.") # Log opcional
        return Response({'message': 'Conexión con Spotify completada.'}, status=status.HTTP_200_OK)
    except SpotifyToken.DoesNotExist:
        # print(f"ASSOCIATE_TOKEN: No se encontró token temporal para state {state_from_frontend}.") # Log opcional
        return Response({'error': 'Sesión de Spotify no encontrada o ya asociada.'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        # print(f"ASSOCIATE_TOKEN: Error asociando token: {e}") # Log opcional
        if SpotifyToken.objects.filter(user=senti_user).exists(): # Si ya tiene uno, podría ser un reintento.
             return Response({'message': 'Ya tienes una conexión con Spotify activa.'}, status=status.HTTP_200_OK)
        return Response({'error': f'Error asociando Spotify: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- Funciones Helper para el Wrapped ---
def refresh_spotify_token(token_obj: SpotifyToken) -> SpotifyToken | None:
    print(f"REFRESH_TOKEN: Iniciando refresco para token ID {token_obj.id}, usuario {token_obj.user.email if token_obj.user else 'N/A (debería tener usuario)'}")
    if not token_obj.refresh_token:
        print("REFRESH_TOKEN: No hay refresh_token en el objeto SpotifyToken. Eliminando token de la BD si está expirado.")
        if token_obj.is_expired: 
            token_obj.delete()
            print("REFRESH_TOKEN: Token expirado y sin refresh_token eliminado.")
        # No se debería llegar aquí si el token no está expirado y no tiene refresh token, es un estado anómalo.
        raise Exception("No refresh token. Re-autenticación necesaria.")
    
    auth_string = f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}"
    auth_base64 = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    headers = {'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/x-www-form-urlencoded'}
    payload = {'grant_type': 'refresh_token', 'refresh_token': token_obj.refresh_token}
    
    print(f"REFRESH_TOKEN: Realizando POST a Spotify con refresh_token: ...{token_obj.refresh_token[-10:]}")
    try:
        response = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=payload, timeout=10)
        print(f"REFRESH_TOKEN: Respuesta de Spotify status: {response.status_code}")
        if response.status_code != 200:
            print(f"REFRESH_TOKEN: Contenido de respuesta de error de Spotify: {response.text}")
        response.raise_for_status()

        new_token_info = response.json()
        print(f"REFRESH_TOKEN: Token refrescado exitosamente desde Spotify. Nuevos scopes: '{new_token_info.get('scope')}'")
        token_obj.access_token = new_token_info['access_token']
        token_obj.expires_in = timezone.now() + timedelta(seconds=new_token_info['expires_in'])
        if 'refresh_token' in new_token_info: 
            print("REFRESH_TOKEN: Spotify devolvió un NUEVO refresh_token.")
            token_obj.refresh_token = new_token_info['refresh_token']
        token_obj.scope = new_token_info.get('scope', token_obj.scope) # Actualizar scopes si vienen
        token_obj.save()
        print(f"REFRESH_TOKEN: Nuevo access_token guardado: ...{token_obj.access_token[-10:]}, expira en: {token_obj.expires_in}")
        return token_obj
    except requests.exceptions.RequestException as e:
        error_detail = ""
        error_type_from_spotify = "unknown_error"
        if hasattr(e, 'response') and e.response is not None:
            try: 
                json_response = e.response.json()
                error_detail = json_response.get('error_description', e.response.text)
                error_type_from_spotify = json_response.get('error', 'unknown_error')
                print(f"REFRESH_TOKEN: Error de Spotify - tipo: {error_type_from_spotify}, detalle: {error_detail}")
                if error_type_from_spotify == 'invalid_grant':
                    print("REFRESH_TOKEN: Refresh token inválido ('invalid_grant'). Eliminando token de la BD.")
                    token_obj.delete()
                    raise Exception(f"Refresh token inválido ('invalid_grant'). Token eliminado. {error_detail}. Se requiere re-autenticación.")
            except ValueError: 
                error_detail = e.response.text
                print(f"REFRESH_TOKEN: Error de Spotify (respuesta no JSON): {error_detail}")
        
        print(f"REFRESH_TOKEN: Excepción completa al refrescar token: {e} - Detalle: {error_detail}")
        # Si no es invalid_grant, el token podría seguir existiendo pero ser problemático.
        # Devolver None aquí podría ser una opción para indicar que no se pudo obtener un token válido.
        # No se elimina el token aquí a menos que sea 'invalid_grant' para no perder el refresh_token si fue un error temporal.
        raise Exception(f"Error refrescando token (tipo: {error_type_from_spotify}): {e} - {error_detail}")

def get_user_valid_spotify_token(user: Usuario) -> SpotifyToken | None:
    print(f"GET_VALID_TOKEN: Buscando token para usuario: {user.email}")
    try:
        token_obj = SpotifyToken.objects.get(user=user)
        print(f"GET_VALID_TOKEN: Token encontrado. ID: {token_obj.id}. Scopes: '{token_obj.scope}'. Expira en: {token_obj.expires_in}. ¿Expirado? {token_obj.is_expired}")
        if token_obj.is_expired:
            print("GET_VALID_TOKEN: Token está expirado. Intentando refrescar...")
            return refresh_spotify_token(token_obj)
        print("GET_VALID_TOKEN: Token es válido y no está expirado.")
        return token_obj
    except SpotifyToken.DoesNotExist:
        print(f"GET_VALID_TOKEN: No se encontró token para el usuario {user.email}.")
        return None
    except Exception as e: # Captura excepciones de refresh_spotify_token
        print(f"GET_VALID_TOKEN: Excepción durante get/refresh para {user.email}: {e}")
        # Si refresh_spotify_token lanza una excepción (ej. por 'invalid_grant'),
        # se propaga aquí. El return None es implícito si la función no retorna antes.
        # Pero para ser explícito:
        return None # No se pudo obtener un token válido

def spotify_api_request(access_token: str, endpoint: str, params: dict | None = None) -> dict | None:
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    full_url = f"{SPOTIFY_API_BASE_URL}{endpoint}"
    print(f"SPOTIFY_API_REQUEST: Realizando GET a {full_url}")
    if params: print(f"SPOTIFY_API_REQUEST: Con params: {str(params)[:200]}...") # Mostrar solo parte de los params si son largos
    print(f"SPOTIFY_API_REQUEST: Usando token: ...{access_token[-10:]}")
    
    try:
        response = requests.get(full_url, headers=headers, params=params or {}, timeout=15) # Aumentado timeout un poco
        print(f"SPOTIFY_API_REQUEST: Respuesta de Spotify status: {response.status_code} para {endpoint}")
        if response.status_code not in [200, 204]: # 204 es No Content, a veces usado.
            print(f"SPOTIFY_API_REQUEST: Contenido de respuesta de error/inesperada de Spotify ({endpoint}): {response.text[:500]}...") # Mostrar inicio del error
        response.raise_for_status() # Esto lanzará HTTPError para 4xx/5xx
        
        if response.status_code == 204:
            return {'success': True} # Para endpoints que no devuelven contenido en 204
        return response.json()
    except requests.exceptions.HTTPError as http_err: # Captura específica de errores HTTP
        print(f"Error HTTP en API request a {endpoint}: {http_err}")
        print(f"SPOTIFY_API_REQUEST (HTTPError): Status: {http_err.response.status_code}, Content: {http_err.response.text[:500]}...")
        return None # Devuelve None en caso de error HTTP
    except requests.exceptions.RequestException as e: # Otros errores de request (timeout, connection error)
        print(f"Error genérico en API request a {endpoint}: {e}")
        return None


# --- Función de Groq con Prompts Ajustados ---
def get_insight_from_groq(prompt_text: str, system_message_key: str = "default", model_name: str = "llama3-70b-8192", max_tokens: int = 60) -> str:
    system_messages = {
        "default": (
            "Eres Senti, un psicólogo musical con un toque poético y conciso. Creas insights para un 'Wrapped' personalizado. "
            "Tus respuestas son frases cortas (1-2 MÁXIMO), impactantes, positivas y reveladoras. "
            "Conectas la música con emociones o facetas de la personalidad de forma memorable. Evita la jerga. Siempre en español."
        ),
        "profile_summary": (
            "Eres Senti, un bardo moderno. Destilas la esencia de alguien por su música para un 'Wrapped' final. "
            "Basado en el resumen, acuña un 'Arquetipo Sonoro-Emocional' (2-3 palabras evocadoras). "
            "Describe el arquetipo en UNA frase poética y perspicaz. "
            f"Luego, de la lista: {', '.join(SENTI_TOOLS_LIST)}. Elige UNA herramienta Senti y justifica en UNA frase por qué complementa al arquetipo. "
            "Formato EXACTO:\n"
            "Arquetipo: [Nombre Arquetipo]\n"
            "Descripcion: [Tu frase poética]\n"
            "SugerenciaSenti: [Herramienta Senti elegida]: [Tu frase de justificación]"
        ),
        "artist_deep_dive": (
            "Eres Senti, analista musical y psicólogo. Para un 'Wrapped', reflexionas sobre un artista que el usuario escucha. "
            "Considerando los temas comunes del artista (conocimiento general), ¿qué podría estar buscando o expresando el usuario? "
            "Da UNA frase reveladora, concisa y psicológica."
        ),
        "song_meaning": (
            "Eres Senti, intérprete de melodías del alma. Para un 'Wrapped', analizas una canción importante para el usuario. "
            "Considerando sus características sonoras (ej. valencia, energía, tempo) y el contexto general, ¿qué necesidad emocional o anhelo profundo podría encapsular? "
            "UNA frase poética y breve."
        )
    }
    selected_system_message = system_messages.get(system_message_key, system_messages["default"])
    
    # print(f"GROQ_API: Solicitando insight con key '{system_message_key}', max_tokens={max_tokens}") # Log opcional
    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": selected_system_message},
                {"role": "user", "content": prompt_text}
            ],
            model=model_name, temperature=0.65, max_tokens=max_tokens
        )
        response_content = chat_completion.choices[0].message.content.strip()
        # print(f"GROQ_API: Respuesta recibida: '{response_content[:100]}...'") # Log opcional
        return response_content
    except Exception as e:
        print(f"Error llamando a Groq API ({model_name}, key: {system_message_key}): {e}")
        if system_message_key == "profile_summary": 
            return "Arquetipo: Alma Melódica\nDescripcion: Tu música es tu eco interior.\nSugerenciaSenti: Diario Emocional Guiado: Para plasmar tus sentires."
        return "Tu música es un lenguaje único, sigue escuchando tu interior."

# --- Vista Principal del WRAPPED PSICOLÓGICO MEJORADO ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def generate_wrapped_view(request):
    user = request.user
    user_display_name = user.nombre.split(' ')[0] if user.nombre and user.nombre.strip() else (user.email.split('@')[0] if user.email else "Alma Sonora")

    print(f"WRAPPED_VIEW: Iniciando para {user_display_name} (Email: {user.email})")

    spotify_token_obj = get_user_valid_spotify_token(user)
    if not spotify_token_obj or not spotify_token_obj.access_token:
     print(f"WRAPPED_VIEW: Token de Spotify no válido o no encontrado para {user.email}. Proceso detenido.")
     return Response({'error': 'Token de Spotify no válido. Por favor, (re)conecta tu cuenta de Spotify en la configuración.'}, status=status.HTTP_400_BAD_REQUEST)

    access_token = spotify_token_obj.access_token
    print(f"DEBUG_POSTMAN: El access_token completo es: {access_token}") # <--- ¡AÑADE ESTA LÍNEA!
    print(f"WRAPPED_VIEW: Usando access_token ...{access_token[-10:]} para {user.email}") # Esta línea ya la tenías y es útil
# ...
    
    generated_stories = []
    all_fetched_data = {} 
    analyzed_data_cache = {}

    # --- Recolección de Datos Primarios (Enfocada en Medium Term) ---
    print("WRAPPED_VIEW: Recolectando datos de Spotify (últimos 6 meses)...")
    
    all_fetched_data['mt_top_tracks'] = spotify_api_request(access_token, 'me/top/tracks', {'time_range': 'medium_term', 'limit': 50})
    all_fetched_data['mt_top_artists'] = spotify_api_request(access_token, 'me/top/artists', {'time_range': 'medium_term', 'limit': 20})
    
    if not all_fetched_data['mt_top_tracks'] or not all_fetched_data['mt_top_artists']:
        print(f"WRAPPED_VIEW: Error obteniendo top tracks o top artists para {user.email}. No se puede continuar.")
        return Response({'error': 'No se pudieron obtener tus datos principales de Spotify. Inténtalo más tarde.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    mt_track_ids = set()
    if all_fetched_data['mt_top_tracks'].get('items'):
        for track in all_fetched_data['mt_top_tracks']['items']:
            if track and track.get('id'): mt_track_ids.add(track['id'])
    print(f"WRAPPED_VIEW: IDs de top tracks recolectados: {len(mt_track_ids)}")

    audio_features_map = {}
    if mt_track_ids:
        track_id_list = list(mt_track_ids)
        print(f"WRAPPED_VIEW: Solicitando audio_features para {len(track_id_list)} tracks...")
        
        # ===== INICIO DE PRUEBA CON UN SOLO ID (DESCOMENTAR PARA PROBAR) =====
        track_id_list = ["5enCBu8FLjlLz60k9t15MA"] # Reemplaza con un ID real
        print(f"WRAPPED_VIEW: DEBUG - Probando audio_features con un solo Track ID: {track_id_list[0]}")
        # ===== FIN DE PRUEBA CON UN SOLO ID =====

        for i in range(0, len(track_id_list), 100): 
            chunk = track_id_list[i:i+100]
            print(f"WRAPPED_VIEW: Solicitando chunk de audio_features (tamaño: {len(chunk)}). IDs: {','.join(chunk)[:50]}...") # Mostrar algunos IDs
            features_data = spotify_api_request(access_token, 'audio-features', {'ids': ",".join(chunk)})
            
            if features_data and features_data.get('audio_features'):
                valid_features_count = 0
                for f_item in features_data['audio_features']:
                    if f_item and f_item.get('id'): # Asegurarse que el feature no sea None
                        audio_features_map[f_item['id']] = f_item
                        valid_features_count +=1
                print(f"WRAPPED_VIEW: Recibidas {valid_features_count} audio_features válidas para el chunk.")
            else:
                # ESTE ES UN PUNTO CRÍTICO SI FALLA
                print(f"WRAPPED_VIEW: ERROR o respuesta vacía al obtener audio_features para el chunk. features_data: {features_data}")
                # Si falla aquí, audio_features_map estará incompleto o vacío.
    
    all_fetched_data['audio_features_map'] = audio_features_map
    print(f"WRAPPED_VIEW: Total audio features obtenidas para {len(audio_features_map)} tracks (medium term).")

    # Si audio_features_map está vacío, muchas historias no se generarán.
    if not audio_features_map and mt_track_ids : # Solo mostrar alerta si se esperaban features
        print(f"WRAPPED_VIEW: ¡ALERTA! audio_features_map está VACÍO a pesar de tener track IDs. Esto limitará severamente las historias generadas para {user.email}.")

    mt_track_items_raw = all_fetched_data['mt_top_tracks'].get('items', [])
    mt_tracks_with_features = [
        track for track in mt_track_items_raw 
        if track and track.get('id') in audio_features_map and audio_features_map[track['id']] is not None
    ]
    print(f"WRAPPED_VIEW: Tracks con features válidas: {len(mt_tracks_with_features)}")


    if mt_tracks_with_features:
        mood_stats = {}
        feature_keys = ['valence', 'energy', 'danceability', 'acousticness', 'instrumentalness', 'speechiness', 'tempo']
        for key in feature_keys:
            values = [audio_features_map[t['id']][key] for t in mt_tracks_with_features if audio_features_map[t['id']] and audio_features_map[t['id']].get(key) is not None]
            if values:
                mood_stats[key] = statistics.mean(values)
            else:
                mood_stats[key] = 0.0 # Asegurar que sea float si no hay valores
        
        minor_modes = sum(1 for t in mt_tracks_with_features if audio_features_map[t['id']] and audio_features_map[t['id']].get('mode') == 0)
        total_modes = sum(1 for t in mt_tracks_with_features if audio_features_map[t['id']] and audio_features_map[t['id']].get('mode') is not None)
        mood_stats['minor_mode_pct'] = (minor_modes / total_modes) * 100 if total_modes > 0 else 0.0
        analyzed_data_cache['semester_mood'] = mood_stats
        print(f"WRAPPED_VIEW: Mood Semestral calculado: V:{mood_stats.get('valence',0):.2f}, E:{mood_stats.get('energy',0):.2f}")
    else:
        print(f"WRAPPED_VIEW: No hay tracks con features, no se calculará semester_mood.")


    # === INICIO DE GENERACIÓN DE STORIES ===
    generated_stories.append({
        'type': 'intro', 'title': f'¡Hola, {user_display_name}!',
        'text': 'Tu música de los últimos 6 meses es un eco de tu ser. ¡Descubrámoslo!',
        'icon': 'Sparkles'
    })

    # STORY 1: Tu Mood General del Semestre
    if 'semester_mood' in analyzed_data_cache:
        try:
            mood_stats = analyzed_data_cache['semester_mood']
            valence_pct = mood_stats.get('valence', 0) * 100
            energy_pct = mood_stats.get('energy', 0) * 100
            danceability_pct = mood_stats.get('danceability', 0) * 100

            mood_description = f"Tu semestre ha sonado con una valencia emocional del {valence_pct:.0f}%, una energía del {energy_pct:.0f}%, y un ritmo para bailar del {danceability_pct:.0f}%."
            
            generated_stories.append({
                'type': 'emotional_landscape',
                'title': '¿Cómo ha sonado tu semestre?',
                'text': mood_description,
                'icon': 'Heart',
                'mood_description': mood_description,
                'data_summary': f"Valencia Emocional: {valence_pct:.0f}%\nEnergía: {energy_pct:.0f}%\nBailabilidad: {danceability_pct:.0f}%"
            })
        except Exception as ex:
            print(f"Error generando historia de mood (STORY 1): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 1 (emotional_landscape) por falta de semester_mood.")


    # STORY 2: Tu Artista Principal del Semestre y su Espejo Emocional
    top_artist_mt = all_fetched_data['mt_top_artists'].get('items', [{}])[0] if all_fetched_data.get('mt_top_artists') and all_fetched_data['mt_top_artists'].get('items') else None
    if top_artist_mt and top_artist_mt.get('name'):
        try:
            mood = analyzed_data_cache.get('semester_mood', {'valence': 0.0, 'energy': 0.0}) # Fallback para mood
            top_genre = top_artist_mt.get('genres', ["género desconocido"])[0]
            prompt = (
                f"Mi artista favorito es '{top_artist_mt.get('name')}'. "
                f"Suelo escuchar géneros como '{top_genre}'. "
                f"Mi música tiene valencia promedio {mood.get('valence', 0):.2f} y energía {mood.get('energy', 0):.2f}. "
                "Analiza profundamente qué revela esto sobre mis necesidades emocionales, aspiraciones, etapa vital o posibles conflictos internos. "
                "Utiliza conocimiento general sobre el artista, su historia, letras y estilo. Relaciona su música y mensaje con mi mundo interior, posibles anhelos, heridas o búsquedas personales. Sé interpretativo, no obvio, y conecta con procesos psicológicos o existenciales. Dame un insight psicológico profundo, evocador y personalizado."
            )
            insight = get_insight_from_groq(prompt, system_message_key="artist_deep_dive", max_tokens=90)
            generated_stories.append({
                'type': 'artist_psychological_insight',
                'title': 'Tu Artista y Tú',
                'text': insight,
                'icon': 'User',
                'artist_name': top_artist_mt.get('name'),
                'artist_image': top_artist_mt.get('images', [{}])[0].get('url') if top_artist_mt.get('images') else None,
            })
        except Exception as ex:
            print(f"Error generando historia de artista (STORY 2): {ex}")
            generated_stories.append({ # Fallback story
                'type': 'artist_psychological_insight',
                'title': 'Tu Artista y Tú',
                'text': f"Tu afinidad con {top_artist_mt.get('name')} revela una conexión emocional especial.",
                'icon': 'User',
                'artist_name': top_artist_mt.get('name'),
                'artist_image': top_artist_mt.get('images', [{}])[0].get('url') if top_artist_mt.get('images') else None,
            })
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 2 (artist_psychological_insight) por falta de top_artist_mt.")


    # STORY 3: Tu Canción Himno del Semestre (más profunda)
    top_song_mt_raw = mt_track_items_raw[0] if mt_track_items_raw else None
    if top_song_mt_raw and top_song_mt_raw.get('id') in audio_features_map and audio_features_map[top_song_mt_raw['id']] is not None:
        try:
            features = audio_features_map[top_song_mt_raw['id']]
            prompt = (
                f"Mi canción más escuchada es '{top_song_mt_raw.get('name')}' de {top_song_mt_raw.get('artists', [{}])[0].get('name', 'Artista Desconocido')}. "
                f"Características: valencia {features.get('valence', 0):.2f}, energía {features.get('energy', 0):.2f}, tempo {features.get('tempo', 0):.0f}. "
                "Interpreta el significado profundo de esta elección en mi vida. Considera la letra, energía, contexto social, historia del artista y posibles mensajes ocultos. "
                "¿Qué anhelos, emociones, heridas, deseos o procesos psicológicos puede estar reflejando esta canción en mi momento vital? Sé interpretativo, conecta con mi mundo interior y evita respuestas superficiales. Dame un insight psicológico, poético y personalizado."
            )
            insight = get_insight_from_groq(prompt, system_message_key="song_meaning", max_tokens=90)
            generated_stories.append({
                'type': 'top_song_psychological_insight',
                'title': 'Tu Canción Más Escuchada',
                'text': insight,
                'icon': 'Music',
                'song_name': top_song_mt_raw.get('name'),
                'song_artist': top_song_mt_raw.get('artists', [{}])[0].get('name', 'Artista Desconocido'),
                'song_image': top_song_mt_raw.get('album', {}).get('images', [{}])[0].get('url') if top_song_mt_raw.get('album', {}).get('images') else None,
            })
        except Exception as ex:
            print(f"Error generando historia de canción top (STORY 3): {ex}")
            generated_stories.append({ # Fallback story
                'type': 'top_song_psychological_insight',
                'title': 'Tu Canción Más Escuchada',
                'text': f"Tu conexión con '{top_song_mt_raw.get('name')}' es significativa y revela mucho de tu mundo interior.",
                'icon': 'Music',
                'song_name': top_song_mt_raw.get('name'),
                'song_artist': top_song_mt_raw.get('artists', [{}])[0].get('name', 'Artista Desconocido'),
                'song_image': top_song_mt_raw.get('album', {}).get('images', [{}])[0].get('url') if top_song_mt_raw.get('album', {}).get('images') else None,
            })
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 3 (top_song_psychological_insight) por falta de top_song_mt_raw o sus features.")

    # STORY 4: Energía Sonora: ¿Impulso o Calma?
    if 'semester_mood' in analyzed_data_cache and 'energy' in analyzed_data_cache['semester_mood']:
        try:
            energy_level = analyzed_data_cache['semester_mood']['energy']
            energy_desc = "vibrante y energética" if energy_level > 0.6 else ("equilibrada" if energy_level > 0.4 else "tranquila y reflexiva")
            generated_stories.append({
                'type': 'energy_analysis',
                'title': 'Tu Energía Musical',
                'text': f"Tu playlist del semestre ha sido principalmente {energy_desc}.",
                'icon': 'Zap',
                'data_summary': f"Nivel de Energía Promedio: {energy_level*100:.0f}%"
            })
        except Exception as ex:
            print(f"Error generando historia de energía (STORY 4): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 4 (energy_analysis) por falta de semester_mood o energy data.")

    # STORY 5: Tu Paleta de Géneros del Semestre
    if all_fetched_data.get('mt_top_artists') and all_fetched_data['mt_top_artists'].get('items'):
        try:
            genre_counter = Counter()
            for artist in all_fetched_data['mt_top_artists']['items']:
                for genre in artist.get('genres', []):
                    genre_counter[genre] += 1
            top_genres_raw = genre_counter.most_common(5)
            total_top_genre_count = sum(count for genre, count in top_genres_raw)
            genre_data = []
            if total_top_genre_count > 0:
                 genre_data = [{'name': genre.capitalize(), 'percentage': (count / total_top_genre_count) * 100} for genre, count in top_genres_raw]
            if genre_data: # Solo añadir si hay datos de género
                generated_stories.append({
                    'type': 'genre_spectrum',
                    'title': 'Tu Espectro Musical',
                    'text': 'Estos géneros han pintado tu semestre.',
                    'icon': 'Palette',
                    'top_genres_data': genre_data
                })
            else:
                print("WRAPPED_VIEW: Omitiendo STORY 5 (genre_spectrum) porque no se pudieron calcular datos de género.")
        except Exception as ex:
            print(f"Error generando historia de géneros (STORY 5): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 5 (genre_spectrum) por falta de mt_top_artists.")


    # STORY 6: Modo Musical (Acústico vs Electrónico)
    if 'semester_mood' in analyzed_data_cache and 'acousticness' in analyzed_data_cache['semester_mood']:
        try:
            acousticness = analyzed_data_cache['semester_mood'].get('acousticness', 0)
            mood_type = "acústico y orgánico" if acousticness > 0.5 else ("mixto" if acousticness > 0.2 else "electrónico y producido")
            generated_stories.append({
                'type': 'acoustic_electronic',
                'title': 'Tu Modo Musical',
                'text': f"Tu sonido ha sido principalmente {mood_type}.",
                'icon': 'Guitar' if acousticness > 0.5 else 'Radio',
                'highlights_list': [
                    f"Nivel de Acústica: {acousticness*100:.0f}%",
                    f"Tendencia: {'Sonidos Naturales' if acousticness > 0.5 else ('Balanceado' if acousticness > 0.2 else 'Sonidos Producidos')}"
                ]
            })
        except Exception as ex:
            print(f"Error generando historia de modo musical (STORY 6): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 6 (acoustic_electronic) por falta de semester_mood o acousticness data.")


    # STORY 7: Canción para el Alma (Introspectiva)
    if mt_tracks_with_features:
        try:
            soul_song = min(mt_tracks_with_features, key=lambda x: (audio_features_map[x['id']].get('valence', 1) * 0.5 + audio_features_map[x['id']].get('energy', 1) * 0.5))
            song_img_url = soul_song.get('album', {}).get('images', [{}])[0].get('url') if soul_song.get('album', {}).get('images') else None
            generated_stories.append({
                'type': 'introspective_song',
                'title': 'Tu Momento de Reflexión',
                'text': 'Esta canción ha tocado las fibras más profundas.',
                'icon': 'CloudRain',
                'song_name': soul_song.get('name', 'Canción Desconocida'),
                'song_artist': soul_song.get('artists', [{}])[0].get('name', 'Artista Desconocido'),
                'song_image': song_img_url,
                'data_summary': 'Un momento para conectar con tus emociones más profundas.'
            })
        except (ValueError, IndexError, TypeError, KeyError) as ex: # Errores comunes al procesar listas/diccionarios
            print(f"Error generando historia de canción del alma (STORY 7): {ex}. Podría ser por lista vacía de mt_tracks_with_features o datos faltantes.")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 7 (introspective_song) por falta de mt_tracks_with_features.")


    # STORY 8: Tu Canción de Amor
    if mt_tracks_with_features:
        try:
            love_song = max(mt_tracks_with_features, key=lambda x: (audio_features_map[x['id']].get('valence', 0) * 0.7 + (1 - abs(audio_features_map[x['id']].get('tempo', 120) - 100)/100) * 0.3))
            song_img_url = love_song.get('album', {}).get('images', [{}])[0].get('url') if love_song.get('album', {}).get('images') else None
            valence_val = audio_features_map[love_song['id']].get('valence', 0) * 100
            tempo_val = audio_features_map[love_song['id']].get('tempo', 0)
            generated_stories.append({
                'type': 'love_song',
                'title': 'Tu Melodía de Amor',
                'text': 'La canción que ha acompañado tus momentos más románticos.',
                'icon': 'Heart',
                'song_name': love_song.get('name', 'Canción Desconocida'),
                'song_artist': love_song.get('artists', [{}])[0].get('name', 'Artista Desconocido'),
                'song_image': song_img_url,
                'data_summary': f"Valencia: {valence_val:.0f}%\nTempo: {tempo_val:.0f} BPM"
            })
        except (ValueError, IndexError, TypeError, KeyError) as ex:
            print(f"Error generando historia de canción de amor (STORY 8): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 8 (love_song) por falta de mt_tracks_with_features.")

    # STORY 9: Tu Canción de Superación
    if mt_tracks_with_features:
        try:
            empowerment_song = max(mt_tracks_with_features, key=lambda x: (audio_features_map[x['id']].get('energy', 0) * 0.6 + audio_features_map[x['id']].get('valence', 0) * 0.4))
            song_img_url = empowerment_song.get('album', {}).get('images', [{}])[0].get('url') if empowerment_song.get('album', {}).get('images') else None
            energy_val = audio_features_map[empowerment_song['id']].get('energy', 0) * 100
            valence_val = audio_features_map[empowerment_song['id']].get('valence', 0) * 100
            generated_stories.append({
                'type': 'motivation_song',
                'title': 'Tu Himno de Superación',
                'text': 'Esta canción te ha dado fuerza cuando más lo necesitabas.',
                'icon': 'Rocket',
                'song_name': empowerment_song.get('name', 'Canción Desconocida'),
                'song_artist': empowerment_song.get('artists', [{}])[0].get('name', 'Artista Desconocido'),
                'song_image': song_img_url,
                'data_summary': f"Energía: {energy_val:.0f}%\nMotivación: {valence_val:.0f}%"
            })
        except (ValueError, IndexError, TypeError, KeyError) as ex:
            print(f"Error generando historia de canción de superación (STORY 9): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 9 (motivation_song) por falta de mt_tracks_with_features.")

    # STORY 10: Tu Canción de Melancolía
    if mt_tracks_with_features:
        try:
            melancholy_song = min(mt_tracks_with_features, key=lambda x: (audio_features_map[x['id']].get('valence', 1) * 0.5 + audio_features_map[x['id']].get('energy', 1) * 0.5))
            song_img_url = melancholy_song.get('album', {}).get('images', [{}])[0].get('url') if melancholy_song.get('album', {}).get('images') else None
            valence_val = audio_features_map[melancholy_song['id']].get('valence', 0)
            generated_stories.append({
                'type': 'melancholy_song',
                'title': 'Tu Melodía Melancólica',
                'text': 'La canción que ha acompañado tus momentos más reflexivos.',
                'icon': 'Cloud',
                'song_name': melancholy_song.get('name', 'Canción Desconocida'),
                'song_artist': melancholy_song.get('artists', [{}])[0].get('name', 'Artista Desconocido'),
                'song_image': song_img_url,
                'data_summary': f"Melancolía (100% - Valencia): {(1-valence_val)*100:.0f}%"
            })
        except (ValueError, IndexError, TypeError, KeyError) as ex:
            print(f"Error generando historia de canción melancólica (STORY 10): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 10 (melancholy_song) por falta de mt_tracks_with_features.")

    # STORY 11: Top 3 Artistas y sus Vibes
    if all_fetched_data.get('mt_top_artists') and all_fetched_data['mt_top_artists'].get('items') and len(all_fetched_data['mt_top_artists']['items']) > 0 :
        try:
            top_3_artists_raw = all_fetched_data['mt_top_artists']['items'][:3]
            artists_data_list = []
            for artist_item in top_3_artists_raw:
                artist_img_url = artist_item.get('images', [{}])[0].get('url') if artist_item.get('images') else None
                artists_data_list.append({
                    'name': artist_item.get('name', 'Artista Desconocido'),
                    'image': artist_img_url,
                    'genres': ', '.join(artist_item.get('genres', [])[:3]).capitalize() if artist_item.get('genres') else 'Géneros no disponibles'
                })
            if artists_data_list: # Solo añadir si hay datos
                generated_stories.append({
                    'type': 'top_artists_showcase',
                    'title': 'Tu Trío de Artistas',
                    'text': 'Estos artistas han definido tu soundtrack personal.',
                    'icon': 'Users',
                    'artists_data': artists_data_list
                })
            else:
                 print("WRAPPED_VIEW: Omitiendo STORY 11 (top_artists_showcase) porque no se procesaron artistas.")
        except Exception as ex:
            print(f"Error generando historia de top artistas (STORY 11): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 11 (top_artists_showcase) por falta de mt_top_artists o items.")

    # STORY 12: Tu Baile Favorito
    if mt_tracks_with_features:
        try:
            dance_song = max(mt_tracks_with_features, key=lambda x: audio_features_map[x['id']].get('danceability', 0))
            song_img_url = dance_song.get('album', {}).get('images', [{}])[0].get('url') if dance_song.get('album', {}).get('images') else None
            danceability_val = audio_features_map[dance_song['id']].get('danceability', 0) * 100
            energy_val = audio_features_map[dance_song['id']].get('energy', 0) * 100
            generated_stories.append({
                'type': 'dance_song',
                'title': 'Tu Ritmo de Baile',
                'text': 'Esta canción te hace mover sin pensarlo.',
                'icon': 'Music4', # Asegúrate que este icono exista en tu frontend
                'song_name': dance_song.get('name', 'Canción Desconocida'),
                'song_artist': dance_song.get('artists', [{}])[0].get('name', 'Artista Desconocido'),
                'song_image': song_img_url,
                'data_summary': f"Bailabilidad: {danceability_val:.0f}%\nEnergía: {energy_val:.0f}%"
            })
        except (ValueError, IndexError, TypeError, KeyError) as ex:
            print(f"Error generando historia de canción bailable (STORY 12): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 12 (dance_song) por falta de mt_tracks_with_features.")

    # STORY 13: Tus Estados de Ánimo (Resumen de Mood)
    if 'semester_mood' in analyzed_data_cache:
        try:
            mood_stats = analyzed_data_cache['semester_mood']
            highlights = [
                f"Momentos Felices (Valencia): {mood_stats.get('valence',0)*100:.0f}%",
                f"Momentos Energéticos: {mood_stats.get('energy',0)*100:.0f}%",
                f"Momentos de Baile: {mood_stats.get('danceability',0)*100:.0f}%",
                f"Momentos Reflexivos (1-Valencia): {(1-mood_stats.get('valence',0))*100:.0f}%"
            ]
            generated_stories.append({
                'type': 'journey_summary_highlights',
                'title': 'Tu Mapa Emocional',
                'text': 'Así se ha movido tu brújula emocional este semestre.',
                'icon': 'Compass',
                'highlights_list': highlights
            })
        except Exception as ex:
            print(f"Error generando historia de estados de ánimo (STORY 13): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 13 (journey_summary_highlights) por falta de semester_mood.")

    # STORY 14: Top 5 Canciones
    if mt_tracks_with_features and len(mt_tracks_with_features) >= 1: # Ajustado para al menos 1, idealmente 5
        try:
            # Tomar hasta 5, pero manejar si hay menos
            top_songs_to_show = mt_tracks_with_features[:5]
            highlights_list = []
            for i, song_item in enumerate(top_songs_to_show):
                song_title = song_item.get('name', 'Título Desconocido')
                main_artist_name = song_item.get('artists', [{}])[0].get('name', 'Artista Desconocido') if song_item.get('artists') else "Artista Desconocido"
                highlights_list.append(f"{i + 1}. {song_title} - {main_artist_name}")
            
            if highlights_list: # Solo añadir si hay canciones procesadas
                generated_stories.append({
                    'type': 'top_songs',
                    'title': f'Tus Top {len(highlights_list)} del Semestre', # Título dinámico
                    'text': 'Las canciones que más han sonado en tus auriculares.',
                    'icon': 'ListMusic',
                    'highlights_list': highlights_list
                })
            else:
                print("WRAPPED_VIEW: Omitiendo STORY 14 (top_songs) porque no se procesaron canciones top.")
        except Exception as ex:
            print(f"Error generando historia de top canciones (STORY 14): {ex}")
    else:
        print("WRAPPED_VIEW: Omitiendo STORY 14 (top_songs) por falta de mt_tracks_with_features suficientes.")


    # --- STORY FINAL: PERFIL EMOCIONAL Y RECOMENDACIÓN SENTI ---
    print("WRAPPED_VIEW: Generando perfil emocional final...")
    try:
        summary_for_arquetype = f"Resumen del perfil musical de {user_display_name} (últimos 6 meses):\n"
        # Usar fallbacks si los datos no están disponibles
        mood_stats_fallback = {'valence': 0.0, 'energy': 0.0, 'danceability': 0.0}
        mood_stats_to_use = analyzed_data_cache.get('semester_mood', mood_stats_fallback)

        summary_for_arquetype += f"Valencia emocional promedio: {mood_stats_to_use['valence']:.2f} (en escala de 0 a 1).\n"
        summary_for_arquetype += f"Energía promedio: {mood_stats_to_use['energy']:.2f} (en escala de 0 a 1).\n"
        summary_for_arquetype += f"Bailabilidad promedio: {mood_stats_to_use['danceability']:.2f} (en escala de 0 a 1).\n"
        
        if top_artist_mt and top_artist_mt.get('name'):
            summary_for_arquetype += f"Artista más escuchado: {top_artist_mt['name']}.\n"
            if top_artist_mt.get('genres'):
                summary_for_arquetype += f"Géneros principales del artista: {', '.join(top_artist_mt['genres'][:2])}.\n"
        else:
            summary_for_arquetype += "Artista más escuchado: No disponible.\n"


        if top_song_mt_raw and top_song_mt_raw.get('name'):
            summary_for_arquetype += f"Canción más escuchada: {top_song_mt_raw['name']}.\n"
            if top_song_mt_raw.get('id') in audio_features_map and audio_features_map.get(top_song_mt_raw['id']) is not None: # Chequeo adicional
                 song_feat = audio_features_map[top_song_mt_raw['id']]
                 summary_for_arquetype += f"Características de la canción top: Valencia {song_feat.get('valence',0):.2f}, Energía {song_feat.get('energy',0):.2f}.\n"
            else:
                summary_for_arquetype += "Características de la canción top: No disponibles debido a falta de audio features.\n"
        else:
            summary_for_arquetype += "Canción más escuchada: No disponible.\n"

        
        summary_for_arquetype += f"Total de canciones top analizadas con features: {len(mt_tracks_with_features)}.\n"
        
        print(f"WRAPPED_VIEW: Prompt para Groq (profile_summary): {summary_for_arquetype}")
        profile_insight = get_insight_from_groq(
            prompt_text=summary_for_arquetype,
            system_message_key="profile_summary",
            max_tokens=150
        )
        
        arquetipo, descripcion, herramienta_sugerida, justificacion_sugerencia = "Perfil Musical Único", "Tu música cuenta una historia especial.", "Diario Emocional Guiado", "Para explorar más profundamente tu mundo sonoro interior." # Fallbacks

        try:
            lines = profile_insight.strip().split('\n')
            parsed_data = {}
            for line in lines:
                if ': ' in line:
                    key_parsed, value_parsed = line.split(': ', 1)
                    parsed_data[key_parsed.strip()] = value_parsed.strip()
            
            arquetipo = parsed_data.get("Arquetipo", arquetipo)
            descripcion = parsed_data.get("Descripcion", descripcion)
            sugerencia_completa = parsed_data.get("SugerenciaSenti", f"{herramienta_sugerida}: {justificacion_sugerencia}")
            
            if ': ' in sugerencia_completa:
                 herramienta_sugerida, justificacion_sugerencia = sugerencia_completa.split(': ', 1)
            else:
                justificacion_sugerencia = sugerencia_completa
        except Exception as parse_ex:
            print(f"Error parseando perfil emocional de Groq: {parse_ex}. Usando fallback. Respuesta Groq: '{profile_insight}'")

        generated_stories.append({
            'type': 'emotional_profile', 'title': arquetipo, 'text': descripcion,
            'icon': 'Brain', 'recommendation': f"{herramienta_sugerida}: {justificacion_sugerencia}"
        })
        
    except Exception as e:
        print(f"Error crítico generando perfil emocional completo: {e}")
        generated_stories.append({
            'type': 'emotional_profile', 'title': 'Tu Perfil Musical',
            'text': 'Tu música refleja un viaje único y personal. Algunos detalles no pudieron ser procesados esta vez.',
            'icon': 'Brain', 'recommendation': 'Diario Emocional Guiado: Para seguir explorando tu conexión con la música.'
        })

    # STORY: REFLEXIÓN FINAL DEL USUARIO
    generated_stories.append({
        'type': 'user_reflection',
        'title': 'Tu Eco Interior',
        'text': f"Y tú, {user_display_name}, ¿cómo resuena este viaje sonoro en ti? Tu música es tu historia, ¡sigue escribiéndola!",
        'icon': 'HeartHandshake' # Asegúrate que este icono exista
    })

    # Story Outro
    generated_stories.append({
        'type': 'outro',
        'title': 'Sigue la Melodía',
        'text': 'Este es solo un capítulo de tu banda sonora personal. ¡En Senti, tu historia musical continúa!',
        'icon': 'Headphones'
    })

    # Mínimo de historias generadas (intro + perfil + reflexión + outro = 4)
    # Si solo se generan estas 4, es probable que los datos de Spotify fallaron mucho.
    MINIMUM_ACCEPTABLE_STORIES = 5 # Por ejemplo, al menos una historia basada en datos.
    if len(generated_stories) < MINIMUM_ACCEPTABLE_STORIES:
        print(f"ERROR GRAVE: Se generaron muy pocas historias ({len(generated_stories)}) para {user_display_name}. Probablemente faltan datos críticos de Spotify.")
        # Considera si este error debe ser 500 o un 200 con un mensaje especial.
        # Si es un error de nuestra parte (ej. fallo en Groq), podría ser 500.
        # Si es por falta de datos del usuario en Spotify, un 200 con mensaje podría ser mejor.
        return Response({
            'error': 'No se pudieron generar suficientes historias personalizadas. Esto puede deberse a datos insuficientes de Spotify o un problema temporal. Por favor, intenta de nuevo más tarde.',
            'stories': generated_stories # Devolver las pocas que se generaron
        }, status=status.HTTP_200_OK) # O HTTP_500_INTERNAL_SERVER_ERROR si es un fallo nuestro

    print(f"WRAPPED_VIEW: Finalizado. Devolviendo {len(generated_stories)} historias para {user_display_name}")
    return Response({'stories': generated_stories}, status=status.HTTP_200_OK)
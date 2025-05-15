# spotify_insights/views.py
import requests
import base64
from datetime import timedelta # timedelta es del módulo datetime base
import datetime as dt # Renombrado para usar para objetos datetime específicos
import secrets
import statistics # Para calcular promedios
from collections import Counter # Para contar géneros

from django.shortcuts import redirect # render no se usa actualmente pero es bueno tenerlo
from django.conf import settings
from django.utils import timezone
from django.http import HttpResponseBadRequest, HttpResponseServerError # JsonResponse no se usa
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from api.models import Usuario # Asegúrate que la ruta a tu modelo Usuario sea correcta
from .models import SpotifyToken

from groq import Groq # Asegúrate de: pip install groq

# --- Constantes y Configuración ---
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE_URL = "https://api.spotify.com/v1/"
# Ampliamos scopes para obtener más datos
SCOPES = "user-top-read user-read-recently-played user-read-email user-library-read user-follow-read"


# --- Vistas de Autenticación OAuth2 con Spotify ---

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_spotify_oauth_state(request):
    """
    Genera un 'state' para que el frontend lo use en el flujo OAuth de Spotify.
    """
    state = secrets.token_urlsafe(16)
    print(f"get_spotify_oauth_state: Generado state '{state}' para usuario Senti: {request.user.email}")
    return Response({'state': state}, status=status.HTTP_200_OK)


def spotify_redirect_to_provider(request):
    """
    Redirige al usuario a Spotify. El frontend DEBE haber obtenido un 'state'
    previamente y lo pasará aquí como query parameter.
    """
    state_from_frontend = request.GET.get('state')
    if not state_from_frontend:
        return HttpResponseBadRequest("Falta el parámetro 'state'. El frontend debe proporcionarlo.")
    
    print(f"spotify_redirect_to_provider: Recibido state del frontend: {state_from_frontend}")

    auth_params = {
        'client_id': settings.SPOTIFY_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': settings.SPOTIFY_REDIRECT_URI,
        'scope': SCOPES,
        'state': state_from_frontend,
        'show_dialog': 'true', # Fuerza el diálogo de autorización
    }
    auth_url = f"{SPOTIFY_AUTH_URL}?{'&'.join([f'{k}={v}' for k,v in auth_params.items()])}"
    return redirect(auth_url)


def spotify_callback_handler(request):
    """
    Spotify redirige aquí. Intercambia código por tokens.
    Guarda el token con el 'oauth_state_key' para ser reclamado después por el frontend.
    """
    code = request.GET.get('code')
    state_received = request.GET.get('state')
    error = request.GET.get('error')

    # Asegúrate que esta ruta sea la correcta en tu frontend, incluyendo /dashboard/ si aplica
    frontend_loading_page_path = "/dashboard/spotify-wrapped/loading" 
    
    if error:
        print(f"spotify_callback_handler: Error recibido de Spotify: {error}, state: {state_received}")
        frontend_error_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?error_from_spotify={error}&state={state_received or ''}"
        return redirect(frontend_error_url)
    
    if not code or not state_received:
        print("spotify_callback_handler: Faltan 'code' o 'state'.")
        return HttpResponseBadRequest("Respuesta inválida de Spotify: faltan parámetros 'code' o 'state'.")

    print(f"spotify_callback_handler: Recibido code y state='{state_received}' de Spotify.")

    auth_string = f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}"
    auth_base64 = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    headers = {'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/x-www-form-urlencoded'}
    payload = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': settings.SPOTIFY_REDIRECT_URI}

    try:
        response = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=payload)
        response.raise_for_status()
        token_info = response.json()
    except requests.exceptions.RequestException as e:
        print(f"spotify_callback_handler: Error en el intercambio de token con Spotify: {e}")
        frontend_error_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?error_type=token_exchange&state={state_received}"
        return redirect(frontend_error_url)

    access_token = token_info.get('access_token')
    refresh_token = token_info.get('refresh_token') 
    expires_in_seconds = token_info.get('expires_in')
    scope_received = token_info.get('scope')

    if not access_token or not expires_in_seconds:
        print("spotify_callback_handler: Respuesta de token inválida de Spotify.")
        frontend_error_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?error_type=invalid_token_response&state={state_received}"
        return redirect(frontend_error_url)

    try:
        SpotifyToken.objects.filter(oauth_state_key=state_received).delete()
        SpotifyToken.objects.create(
            user=None, oauth_state_key=state_received, access_token=access_token,
            refresh_token=refresh_token, expires_in=timezone.now() + timedelta(seconds=expires_in_seconds),
            token_type=token_info.get('token_type', 'Bearer'), scope=scope_received
        )
        print(f"spotify_callback_handler: Token de Spotify guardado temporalmente con state='{state_received}'.")
    except Exception as e:
        print(f"spotify_callback_handler: ERROR guardando SpotifyToken temporal: {e}")
        frontend_error_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?error_type=db_save_temp_token&state={state_received}"
        return redirect(frontend_error_url)
    
    frontend_success_url = f"{settings.FRONTEND_URL.rstrip('/')}{frontend_loading_page_path}?state={state_received}&code_received=true"
    print(f"spotify_callback_handler: Redirigiendo a frontend: {frontend_success_url}")
    return redirect(frontend_success_url)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def associate_spotify_token(request):
    state_from_frontend = request.data.get('state')
    if not state_from_frontend:
        return Response({'error': "Falta el parámetro 'state' en la solicitud."}, status=status.HTTP_400_BAD_REQUEST)

    senti_user = request.user
    print(f"associate_spotify_token: Intentando asociar token con state='{state_from_frontend}' al usuario Senti: {senti_user.email}")

    try:
        token_to_associate = SpotifyToken.objects.get(oauth_state_key=state_from_frontend, user__isnull=True)
        SpotifyToken.objects.filter(user=senti_user).exclude(pk=token_to_associate.pk).delete()
        token_to_associate.user = senti_user
        token_to_associate.oauth_state_key = None
        token_to_associate.save()
        print(f"associate_spotify_token: Token asociado exitosamente a {senti_user.email}.")
        return Response({'message': 'Conexión con Spotify completada exitosamente.'}, status=status.HTTP_200_OK)
    except SpotifyToken.DoesNotExist:
        print(f"associate_spotify_token: No se encontró token temporal con state='{state_from_frontend}'.")
        return Response({'error': 'No se encontró la sesión de Spotify para asociar. Por favor, intenta conectar de nuevo.'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        print(f"ERROR en associate_spotify_token para {senti_user.email} con state='{state_from_frontend}': {e}")
        if SpotifyToken.objects.filter(user=senti_user).exists():
             print(f"associate_spotify_token: El usuario {senti_user.email} ya tiene un token. Puede ser un reintento.")
             return Response({'message': 'Ya tienes una conexión activa con Spotify.'}, status=status.HTTP_200_OK)
        return Response({'error': f'Ocurrió un error al asociar tu cuenta de Spotify: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- Funciones Helper para el Wrapped ---

def refresh_spotify_token(token_obj: SpotifyToken) -> SpotifyToken | None:
    if not token_obj.refresh_token:
        user_email = token_obj.user.email if token_obj.user else "token no reclamado"
        print(f"No refresh token para {user_email}")
        if token_obj.is_expired: # Solo eliminar si está expirado y no hay refresh token
            print(f"Token expirado y sin refresh token para {user_email}. Eliminando token.")
            token_obj.delete()
        raise Exception("No refresh token disponible. Re-autenticación necesaria.")
    
    auth_string = f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}"
    auth_base64 = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    headers = {'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/x-www-form-urlencoded'}
    payload = {'grant_type': 'refresh_token', 'refresh_token': token_obj.refresh_token}

    try:
        user_email_log = token_obj.user.email if token_obj.user else "token no reclamado"
        print(f"Intentando refrescar token para {user_email_log}")
        response = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=payload)
        response.raise_for_status()
        new_token_info = response.json()

        token_obj.access_token = new_token_info['access_token']
        token_obj.expires_in = timezone.now() + timedelta(seconds=new_token_info['expires_in'])
        token_obj.token_type = new_token_info.get('token_type', 'Bearer')
        if 'refresh_token' in new_token_info:
            token_obj.refresh_token = new_token_info['refresh_token']
        token_obj.save()
        print(f"Token refrescado para {user_email_log}")
        return token_obj
    except requests.exceptions.RequestException as e:
        user_email_log = token_obj.user.email if token_obj.user else "token no reclamado"
        error_message = f"Error al refrescar token de Spotify para {user_email_log}: {e}"
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                error_message += f" - Detalle: {error_detail.get('error_description', e.response.text)}"
                if error_detail.get('error') == 'invalid_grant':
                    print(f"Refresh token inválido para {user_email_log}. El token será eliminado.")
                    token_obj.delete()
                    raise Exception("Refresh token inválido. Re-autenticación necesaria.")
            except ValueError:
                error_message += f" - Respuesta no JSON: {e.response.text}"
        print(f"ERROR en refresh_spotify_token: {error_message}")
        raise Exception(f"No se pudo refrescar el token de Spotify: {error_message}")


def get_user_valid_spotify_token(user: Usuario) -> SpotifyToken | None:
    try:
        token_obj = SpotifyToken.objects.get(user=user)
        if token_obj.is_expired:
            print(f"Token para {user.email} expirado. Intentando refrescar...")
            return refresh_spotify_token(token_obj)
        return token_obj
    except SpotifyToken.DoesNotExist:
        print(f"No se encontró SpotifyToken para el usuario {user.email}")
        return None
    except Exception as e:
        print(f"Error obteniendo/refrescando token para {user.email}: {e}")
        return None

def spotify_api_request(access_token: str, endpoint: str, params: dict | None = None, method: str = 'GET', data: dict | None = None) -> dict | None:
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    full_url = f"{SPOTIFY_API_BASE_URL}{endpoint}"
    # print(f"Spotify API Request: {method.upper()} {full_url} con params: {params}") # Log detallado opcional
    try:
        if method.upper() == 'GET':
            response = requests.get(full_url, headers=headers, params=params or {}, timeout=15)
        elif method.upper() == 'POST':
            response = requests.post(full_url, headers=headers, json=data or {}, params=params or {}, timeout=15)
        else:
            print(f"Método HTTP no soportado: {method}")
            return None
        
        response.raise_for_status()
        if response.status_code == 204:
            return {'success': True, 'status_code': 204}
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        print(f"Error HTTP {http_err.response.status_code} en {method.upper()} {full_url}: {http_err.response.text[:500]}")
    except requests.exceptions.Timeout:
        print(f"Timeout en {method.upper()} {full_url}")
    except requests.exceptions.RequestException as req_err:
        print(f"Error de red en {method.upper()} {full_url}: {req_err}")
    return None

def get_insight_from_groq(prompt_text: str, system_message_key: str = "default", model_name: str = "llama3-70b-8192", max_tokens: int = 150) -> str:
    system_messages = {
        "default": (
            "Eres un psicólogo musical compasivo, elocuente y ligeramente poético. Analizas datos musicales para un 'Wrapped' personalizado. "
            "Ofrece reflexiones de 1-2 frases concisas, positivas y reveladoras, conectando la música con posibles estados emocionales o necesidades internas. "
            "Usa un lenguaje accesible y cálido. Evita diagnósticos. Responde siempre en español."
        ),
        "profile_summary": (
            "Eres un bardo moderno que destila la esencia emocional de una persona a través de su música. "
            "Con base en un resumen de sus hábitos de escucha, acuña un 'Arquetipo Sonoro-Emocional' único y evocador (2-4 palabras). "
            "Describe este arquetipo en 2 frases poéticas y perspicaces. "
            "Finalmente, sugiere una actividad o herramienta de la plataforma de bienestar 'Senti' que nutra o complemente las cualidades de este arquetipo. "
            "Formatea tu respuesta de manera precisa:\n"
            "NombreArquetipo: [El Nombre del Arquetipo]\n"
            "Descripción: [Tu descripción poética]\n"
            "SugerenciaSenti: [Tu sugerencia específica y accionable de Senti]\n"
            "Responde siempre en español."
        )
    }
    selected_system_message = system_messages.get(system_message_key, system_messages["default"])
    print(f"Llamando a Groq (modelo {model_name}, system_key: {system_message_key}, max_tokens: {max_tokens})")
    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": selected_system_message},
                {"role": "user", "content": prompt_text}
            ],
            model=model_name, temperature=0.75, max_tokens=max_tokens
        )
        response_content = chat_completion.choices[0].message.content.strip()
        print(f"Respuesta de Groq (primeros 100 chars): {response_content[:100]}...")
        return response_content
    except Exception as e:
        print(f"Error llamando a Groq API: {e}")
        return "Mientras la IA calibra sus instrumentos, recuerda que tu música ya habla volúmenes de tu singularidad."


# --- Vista Principal para Generar el Wrapped (CON MÁS HISTORIAS Y PROFUNDIDAD) ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def generate_wrapped_view(request):
    user = request.user
    user_display_name = user.first_name or user.username
    print(f"generate_wrapped_view: Iniciando para {user_display_name} ({user.email})")

    spotify_token_obj = get_user_valid_spotify_token(user)
    if not spotify_token_obj or not spotify_token_obj.access_token:
        return Response({'error': 'Token de Spotify no válido. (Re)conecta tu cuenta.'}, status=status.HTTP_400_BAD_REQUEST)
    
    access_token = spotify_token_obj.access_token
    generated_stories = []
    all_fetched_data = {} 
    analyzed_data_cache = {} # Para guardar datos ya analizados

    # Story 0: Intro
    generated_stories.append({
        'type': 'intro', 'title': f'¡Hola de nuevo, {user_display_name}!',
        'text': 'Tu universo musical es un eco de tu alma. Descubramos juntos sus matices más profundos.',
        'icon': 'Sparkles'
    })

    print("Recolectando datos primarios de Spotify...")
    # --- Recolección de Datos Primarios ---
    time_ranges_spotify = {'short_term': 'últimas 4 semanas', 'medium_term': 'últimos 6 meses', 'long_term': 'toda tu historia'}
    
    all_fetched_data['top_tracks'] = {}
    all_fetched_data['top_artists'] = {}

    for term_key in time_ranges_spotify.keys():
        all_fetched_data['top_tracks'][term_key] = spotify_api_request(access_token, 'me/top/tracks', {'time_range': term_key, 'limit': 50})
        all_fetched_data['top_artists'][term_key] = spotify_api_request(access_token, 'me/top/artists', {'time_range': term_key, 'limit': 20})

    thirty_days_ago_ms = int((timezone.now() - timedelta(days=30)).timestamp() * 1000)
    all_fetched_data['recently_played'] = spotify_api_request(access_token, 'me/player/recently-played', {'limit': 50, 'after': thirty_days_ago_ms})
    
    track_ids_for_features = set()
    temp_tracks_for_features_objects = [] # Para tener el objeto track completo
    for term_key in time_ranges_spotify.keys():
        tracks_for_term = all_fetched_data['top_tracks'][term_key]
        if tracks_for_term and tracks_for_term.get('items'):
            for track in tracks_for_term['items']:
                if track and track.get('id') and track['id'] not in track_ids_for_features:
                    track_ids_for_features.add(track['id'])
                    temp_tracks_for_features_objects.append(track) # Guardamos objeto completo
    
    if all_fetched_data['recently_played'] and all_fetched_data['recently_played'].get('items'): 
        for item in all_fetched_data['recently_played']['items']:
            track = item.get('track')
            if track and track.get('id') and track['id'] not in track_ids_for_features:
                track_ids_for_features.add(track['id'])
                temp_tracks_for_features_objects.append(track)

    audio_features_map = {}
    if track_ids_for_features:
        track_id_list = list(track_ids_for_features)
        for i in range(0, len(track_id_list), 100):
            chunk = track_id_list[i:i+100]
            features_data = spotify_api_request(access_token, 'audio-features', {'ids': ",".join(chunk)})
            if features_data and features_data.get('audio_features'):
                for f_item in features_data['audio_features']:
                    if f_item and f_item.get('id'): audio_features_map[f_item['id']] = f_item
    all_fetched_data['audio_features_map'] = audio_features_map
    print(f"Audio features obtenidas para {len(audio_features_map)} tracks únicos.")

    # --- ANÁLISIS DE DATOS PRELIMINARES ---
    mt_track_items = all_fetched_data['top_tracks']['medium_term'].get('items', []) if all_fetched_data['top_tracks'].get('medium_term') else []
    mt_features_list = [audio_features_map[t['id']] for t in mt_track_items if t and t.get('id') in audio_features_map]
    
    analyzed_data_cache['mt_mood'] = {
        'valence': 0.5, 'energy': 0.5, 'danceability': 0.5, 'acousticness': 0.5, 
        'instrumentalness': 0.1, 'speechiness': 0.1, 'minor_mode_pct': 30, 'tempo': 120.0
    }
    if mt_features_list:
        try:
            for key in ['valence', 'energy', 'danceability', 'acousticness', 'instrumentalness', 'speechiness', 'tempo']:
                analyzed_data_cache['mt_mood'][key] = statistics.mean(f[key] for f in mt_features_list if f.get(key) is not None)
            minor_mode_tracks = sum(1 for f in mt_features_list if f.get('mode') == 0)
            analyzed_data_cache['mt_mood']['minor_mode_pct'] = (minor_mode_tracks / len(mt_features_list)) * 100 if mt_features_list else 0
            print(f"Análisis MT: V:{analyzed_data_cache['mt_mood']['valence']:.2f} E:{analyzed_data_cache['mt_mood']['energy']:.2f} etc.")
        except (statistics.StatisticsError, TypeError, KeyError) as stat_err: 
            print(f"Advertencia: Stats MT no calculadas completamente debido a: {stat_err}")
    
    # --- GENERACIÓN DE STORIES ---

    # STORY: Tu Paisaje Emocional Principal
    if mt_features_list:
        try:
            mood_stats = analyzed_data_cache['mt_mood']
            # ... (lógica para final_mood_desc y stat_text como en la respuesta anterior) ...
            mood_desc_parts = []
            if mood_stats['valence'] > 0.65: mood_desc_parts.append("claramente optimista y expansiva")
            elif mood_stats['valence'] < 0.35: mood_desc_parts.append("profundamente introspectiva, a menudo con un toque melancólico")
            else: mood_desc_parts.append("rica en matices emocionales, buscando un equilibrio")

            if mood_stats['energy'] > 0.7: mood_desc_parts.append("e impulsada por una energía vibrante y contagiosa")
            elif mood_stats['energy'] < 0.4: mood_desc_parts.append("y envuelta en una atmósfera de calma y suavidad")
            else: mood_desc_parts.append("y nutrida por una energía adaptable y fluida")
            final_mood_desc = " ".join(mood_desc_parts)
            stat_text = (f"Valencia (Positividad): {mood_stats['valence']:.2f}\n"
                         f"Energía (Intensidad): {mood_stats['energy']:.2f}\n"
                         f"Bailabilidad: {mood_stats['danceability']:.2f}")

            prompt = (f"La música que ha definido mis últimos 6 meses tiende a ser {final_mood_desc} (Valencia: {mood_stats['valence']:.2f}, Energía: {mood_stats['energy']:.2f}). "
                      f"Como psicólogo musical, ¿qué arquetipo emocional o búsqueda interna podría estar reflejando esta constante sonora? "
                      f"Dame una o dos frases poéticas y reveladoras.")
            insight = get_insight_from_groq(prompt, max_tokens=100)
            generated_stories.append({
                'type': 'emotional_landscape', 'title': 'Tu Paisaje Emocional Dominante',
                'mood_description': final_mood_desc.capitalize() + ".", 
                'text': insight, 'data_summary': stat_text, 'icon': 'CloudDrizzle'
            })
            analyzed_data_cache['main_mood_insight_text'] = insight
        except Exception as e: print(f"Error en story 'emotional_landscape': {e}")

    # STORY: Tus 3 Pilares Musicales (Top 3 Artistas Medium Term)
    top_artists_mt_items = all_fetched_data['top_artists']['medium_term'].get('items', []) if all_fetched_data['top_artists'].get('medium_term') else []
    if top_artists_mt_items and len(top_artists_mt_items) >= 1: # Ajustado para funcionar incluso con 1 o 2 artistas
        try:
            # Tomar hasta 3 artistas
            num_artists_to_show = min(len(top_artists_mt_items), 3)
            top_n_artists_mt = top_artists_mt_items[:num_artists_to_show]
            
            artists_data_for_frontend = []
            prompt_artists_parts = []
            for i, artist_obj in enumerate(top_n_artists_mt):
                name = artist_obj.get('name', 'Artista Desconocido')
                img = artist_obj.get('images',[{}])[0].get('url') if artist_obj.get('images') else None
                genres = ", ".join(artist_obj.get('genres', [])[:2])
                artists_data_for_frontend.append({'name': name, 'image': img, 'genres': genres})
                prompt_artists_parts.append(f"{i+1}. {name} ({genres})")
            
            artists_list_str = "\n".join(prompt_artists_parts)
            mt_mood_ctx = analyzed_data_cache.get('mt_mood', {})
            prompt = (f"Mis artistas más influyentes en los últimos 6 meses incluyen:\n{artists_list_str}\n"
                      f"Considerando que mi mood musical general tiende a ser (Valencia: {mt_mood_ctx.get('valence',0.5):.2f}, Energía: {mt_mood_ctx.get('energy',0.5):.2f}), "
                      f"¿qué necesidades emocionales o facetas de mi personalidad podrían estar representando estos artistas en conjunto? Una reflexión concisa.")
            insight = get_insight_from_groq(prompt, max_tokens=180)
            generated_stories.append({
                'type': 'top_artists_showcase', # Cambiado el type para diferenciar
                'title': 'Tus Guías Sonoras Clave', 
                'text': insight, 
                'artists_data': artists_data_for_frontend, 
                'icon': 'Users'
            })
            if artists_data_for_frontend:
                analyzed_data_cache['top_artist_primary'] = artists_data_for_frontend[0]
        except Exception as e: print(f"Error en story 'top_artists_showcase': {e}")

    # STORY: Tu Canción Refugio o "Alma Gemela Musical" (Canción #1 Long Term)
    anchor_song_raw = all_fetched_data['top_tracks']['long_term'].get('items', [{}])[0] if all_fetched_data['top_tracks'].get('long_term') and all_fetched_data['top_tracks']['long_term'].get('items') else None
    if anchor_song_raw and anchor_song_raw.get('id'):
        try:
            # ... (lógica de anchor_song como antes) ...
            s_name = anchor_song_raw.get('name')
            s_artist = anchor_song_raw.get('artists',[{}])[0].get('name') if anchor_song_raw.get('artists') else ""
            s_img = (anchor_song_raw.get('album',{}).get('images',[{}])[0].get('url') if anchor_song_raw.get('album') and anchor_song_raw.get('album').get('images') else None)
            
            if s_name and s_artist:
                s_features = audio_features_map.get(anchor_song_raw.get('id'))
                s_mood_ctx = ""
                if s_features: 
                    s_mood_ctx = (f"Esta canción resuena con una valencia de {s_features['valence']:.2f}, energía de {s_features['energy']:.2f}, "
                                  f"y un tempo de {s_features['tempo']:.0f} BPM. Es predominantemente "
                                  f"{'instrumental' if s_features['instrumentalness'] > 0.6 else ('acústica' if s_features['acousticness'] > 0.7 else 'vocal y producida')}.")

                prompt = (f"Mi canción más escuchada de todos los tiempos, mi 'alma gemela musical', es '{s_name}' por {s_artist}. {s_mood_ctx} "
                          f"Como psicólogo musical, ¿qué necesidad emocional fundamental, valor personal intrínseco o recuerdo persistente podría estar encapsulado en esta melodía que me acompaña a lo largo del tiempo? "
                          f"Una reflexión profunda y emotiva en 2-3 frases.")
                insight = get_insight_from_groq(prompt, max_tokens=200)
                generated_stories.append({
                    'type': 'anchor_song', 'title': 'Tu Alma Gemela Musical', 'song_name': s_name, 'song_artist': s_artist,
                    'song_image': s_img, 'text': insight, 'icon': 'Anchor',
                    'data_summary': s_mood_ctx
                })
                analyzed_data_cache['anchor_song_details'] = {'name': s_name, 'artist': s_artist}
        except Exception as e: print(f"Error en story 'anchor_song': {e}")


    # STORY: Tu Canción Más "Triste" o Introspectiva (basada en baja valencia y energía en MT)
    if mt_track_items: # Necesitamos mt_track_items para esto
        try:
            introspective_candidates = []
            for track_raw in mt_track_items: # Iterar sobre los objetos track completos
                if track_raw and track_raw.get('id') in audio_features_map:
                    features = audio_features_map[track_raw['id']]
                    if features['valence'] < 0.3 and features['energy'] < 0.45:
                        introspective_candidates.append({'raw': track_raw, 'features': features, 'score': (1 - features['valence']) + (1 - features['energy']) })
            
            if introspective_candidates:
                introspective_candidates.sort(key=lambda x: x['score'], reverse=True)
                saddest_song_data = introspective_candidates[0]
                
                s_raw, s_feat = saddest_song_data['raw'], saddest_song_data['features']
                # ... (lógica para s_name, s_artist, s_img como antes) ...
                s_name = s_raw.get('name')
                s_artist = s_raw.get('artists',[{}])[0].get('name') if s_raw.get('artists') else ""
                s_img = (s_raw.get('album',{}).get('images',[{}])[0].get('url') if s_raw.get('album') and s_raw.get('album').get('images') else None)

                stat_text = f"Destaca por su valencia de {s_feat['valence']:.2f} y energía de {s_feat['energy']:.2f}."
                prompt = (f"Entre mis canciones frecuentes, '{s_name}' de {s_artist} resalta por su carácter profundamente introspectivo (valencia {s_feat['valence']:.2f}, energía {s_feat['energy']:.2f}). "
                        f"Cuando me sumerjo en esta canción, ¿qué tipo de procesamiento emocional podría estar facilitando? ¿Es un espacio para la melancolía, la reflexión serena o la aceptación de emociones difíciles? "
                        f"Una frase comprensiva y sin juicios.")
                insight = get_insight_from_groq(prompt, max_tokens=120)
                generated_stories.append({
                    'type': 'introspective_song', 'title': 'Tu Rincón de Sentir Profundo', 
                    'song_name': s_name, 'song_artist': s_artist, 'song_image': s_img, 
                    'text': insight, 'icon': 'Droplets', 
                    'data_summary': stat_text
                })
                analyzed_data_cache['introspective_song_details'] = {'name': s_name, 'artist': s_artist}
        except Exception as e: print(f"Error en story 'introspective_song': {e}")

    # ... (El resto de las stories: 'genre_spectrum', 'time_machine_music', 'journey_summary_highlights', 'emotional_profile', 'outro'
    #      deberían seguir la misma estructura, usando los datos de `all_fetched_data` y `analyzed_data_cache`
    #      y guardando resultados intermedios en `analyzed_data_cache` si son necesarios para el perfil final.)

    # STORY: Tu Espectro de Géneros y lo que Revelan
    all_genres_mt_flat = []
    # ... (código para popular all_genres_mt_flat como en la respuesta anterior) ...
    if all_fetched_data['top_artists']['medium_term'] and all_fetched_data['top_artists']['medium_term'].get('items'):
        for artist in all_fetched_data['top_artists']['medium_term']['items']:
            genres = artist.get('genres', [])
            all_genres_mt_flat.extend(g.lower().replace('-', ' ').replace('_', ' ') for g in genres)
    
    if all_genres_mt_flat:
        try:
            genre_counts = Counter(all_genres_mt_flat)
            total_genre_instances = sum(genre_counts.values()) # Suma de todas las menciones de género
            top_3_genres_with_counts = genre_counts.most_common(3)
            
            if top_3_genres_with_counts:
                genres_data_for_frontend = []
                prompt_genres_parts = []
                for g, c in top_3_genres_with_counts:
                    pct = (c / total_genre_instances) * 100 if total_genre_instances > 0 else 0
                    genres_data_for_frontend.append({'name': g.title(), 'percentage': round(pct)})
                    prompt_genres_parts.append(f"{g.title()} ({pct:.0f}%)")
                
                genres_str_for_prompt = ", ".join(prompt_genres_parts)
                analyzed_data_cache['top_genres_list_for_summary'] = [g['name'] for g in genres_data_for_frontend]

                prompt = (f"Mis géneros dominantes en los últimos 6 meses son: {genres_str_for_prompt}. "
                          f"¿Qué narrativa emocional o búsqueda personal podría estar tejiéndose a través de esta particular constelación de géneros?")
                insight = get_insight_from_groq(prompt, max_tokens=180)
                generated_stories.append({
                    'type': 'genre_spectrum', 'title': 'Tu Ecosistema de Géneros', 
                    'text': insight, 'top_genres_data': genres_data_for_frontend, 
                    'icon': 'Layers'
                })
        except Exception as e: print(f"Error en story 'genre_spectrum': {e}")

    # STORY: Tu Música como Máquina del Tiempo
    release_years_mt = []
    # ... (código para popular release_years_mt como en la respuesta anterior) ...
    if mt_track_items: # Usa mt_track_items que ya tiene los tracks de medium term
        for track in mt_track_items:
            if track and track.get('album') and track['album'].get('release_date'):
                try: 
                    year_str = track['album']['release_date'][:4]
                    if year_str.isdigit(): release_years_mt.append(int(year_str))
                except: pass
    
    if release_years_mt:
        try:
            # ... (lógica para avg_year, median_year, time_focus_desc como antes) ...
            avg_year = statistics.mean(release_years_mt)
            median_year = statistics.median(release_years_mt)
            year_now = dt.datetime.now().year
            
            time_focus_desc = ""
            if median_year > year_now - 3: time_focus_desc = "sintonizas con lo más fresco y actual"
            elif median_year > year_now - 8: time_focus_desc = "vibras principalmente con los sonidos de esta última década"
            elif median_year >= 2000: time_focus_desc = "encuentras un eco especial en la música de los 2000s"
            elif median_year >= 1990: time_focus_desc = "te dejas abrazar por la nostalgia de los 90s"
            else: time_focus_desc = "aprecias los clásicos atemporales"

            stat_text = f"El año de lanzamiento mediano de tu música es {int(median_year)}."
            analyzed_data_cache['time_focus_desc_for_summary'] = time_focus_desc

            prompt = (f"La música que más escucho tiene un año de lanzamiento mediano alrededor de {int(median_year)}, lo que sugiere que {time_focus_desc}. "
                      f"¿Qué podría estar buscando mi psique al conectar predominantemente con esta(s) época(s) musicales? ¿Es confort, descubrimiento, o un reflejo de mi propia etapa vital?")
            insight = get_insight_from_groq(prompt)
            generated_stories.append({'type': 'time_machine_music', 'title': 'Tu Música en el Tiempo', 
                                      'text': insight, 'era_description': time_focus_desc, 'icon': 'History',
                                      'data_summary': stat_text})
        except Exception as e: print(f"Error en story 'time_machine_music': {e}")

    # STORY: RESUMEN DE TU VIAJE SONORO (Highlights)
    summary_highlights_list = []
    if 'top_artist_primary' in analyzed_data_cache:
        summary_highlights_list.append(f"Tu Artista Guía: {analyzed_data_cache['top_artist_primary']['name']}")
    if 'anchor_song_details' in analyzed_data_cache:
        summary_highlights_list.append(f"Tu Canción Eterna: '{analyzed_data_cache['anchor_song_details']['name']}'")
    if 'introspective_song_details' in analyzed_data_cache:
        summary_highlights_list.append(f"Tu Espacio de Reflexión: '{analyzed_data_cache['introspective_song_details']['name']}'")
    
    # Añadir el mood general como highlight
    mood_stats_for_summary = analyzed_data_cache.get('mt_mood', {})
    if mood_stats_for_summary.get('valence') is not None: # Verificar que tengamos los datos
        summary_highlights_list.append(f"Tu Mood General: Valencia {mood_stats_for_summary['valence']:.2f}, Energía {mood_stats_for_summary['energy']:.2f}")

    if len(summary_highlights_list) >= 2:
        generated_stories.append({
            'type': 'journey_summary_highlights',
            'title': 'Ecos de Tu Alma Sonora',
            'text': "Algunos de los reflejos más brillantes de tu viaje musical:",
            'highlights_list': summary_highlights_list, 
            'icon': 'MapPinned'
        })


    # --- STORY FINAL: PERFIL EMOCIONAL Y RECOMENDACIÓN SENTI ---
    try:
        summary_for_arquetype = f"Perfil musical de {user_display_name}:\n"
        mood = analyzed_data_cache.get('mt_mood', {})
        summary_for_arquetype += f"- Paisaje emocional sonoro: Valencia {mood.get('valence',0.5):.2f}, Energía {mood.get('energy',0.5):.2f}, Bailabilidad {mood.get('danceability',0.5):.2f}, Acústica {mood.get('acousticness',0.5):.2f}, Instrumental {mood.get('instrumentalness',0.1):.2f}, Predominio Modo Menor {mood.get('minor_mode_pct',30):.0f}%.\n"
        if 'main_mood_insight_text' in analyzed_data_cache: summary_for_arquetype += f"- Búsqueda emocional principal: \"{analyzed_data_cache['main_mood_insight_text']}\"\n"
        if 'top_genres_list_for_summary' in analyzed_data_cache: summary_for_arquetype += f"- Géneros clave: {', '.join(analyzed_data_cache['top_genres_list_for_summary'])}.\n"
        if 'time_focus_desc_for_summary' in analyzed_data_cache: summary_for_arquetype += f"- Conexión temporal: Su música {analyzed_data_cache['time_focus_desc_for_summary']}.\n"
        if 'top_artist_primary' in analyzed_data_cache: summary_for_arquetype += f"- Artista faro: {analyzed_data_cache['top_artist_primary']['name']}.\n"
        
        print(f"Resumen para perfil/arquetipo Groq: {summary_for_arquetype[:600]}...")

        prompt_arquetype = (
            f"Analiza en profundidad este perfil musical:\n{summary_for_arquetype}\n"
            f"Define un 'Arquetipo Sonoro-Emocional' para esta persona (2-4 palabras, muy creativo, único y evocador, ej: 'El Alquimista de Ecos', 'La Guardiana de Melodías Íntimas'). "
            f"Luego, proporciona una descripción de este arquetipo en 2-3 frases poéticas y profundas que capturen su esencia, sus fortalezas y cómo se relaciona con el mundo y sus emociones a través de la música. "
            f"Finalmente, sugiere una actividad, herramienta o reto específico de la plataforma de bienestar 'Senti' que le ayude a este arquetipo a profundizar en su autoconocimiento o potenciar su bienestar. "
            f"Formatea tu respuesta EXACTAMENTE así (cada etiqueta en una nueva línea, sin texto adicional antes o después):\n"
            "NombreArquetipo: [Aquí el nombre del arquetipo]\n"
            "Descripción: [Aquí tu descripción del arquetipo]\n"
            "SugerenciaSenti: [Aquí tu sugerencia específica de Senti]"
        )
        profile_text_raw = get_insight_from_groq(prompt_arquetype, system_message_key="profile_summary", max_tokens=300)

        profile_name, profile_desc, senti_reco = "Tu Alma Sonora", "Tu música teje historias únicas de tu ser.", "Explora 'Diario Emocional' en Senti."
        try:
            parsed_data = {}
            for line in profile_text_raw.split('\n'):
                if ':' in line:
                    key_part, value_part = line.split(":",1)
                    norm_key = key_part.strip().lower().replace(" ","").replace("_","").replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")
                    parsed_data[norm_key] = value_part.strip()
            
            profile_name = parsed_data.get("nombrearquetipo", profile_name)
            profile_desc = parsed_data.get("descripcion", parsed_data.get("descripción", profile_desc)) # Aceptar ambas
            senti_reco = parsed_data.get("sugerenciasenti", senti_reco)

        except Exception as e_parse: print(f"Error parseando perfil Groq: {e_parse}. Raw: {profile_text_raw}")
        
        generated_stories.append({'type': 'emotional_profile', 'title': profile_name, 'text': profile_desc, 'recommendation': senti_reco, 'icon': 'Award'})
    except Exception as e: 
        print(f"Error generando story 'emotional_profile': {e}")
        generated_stories.append({'type': 'emotional_profile', 'title': 'Tu Esencia Musical', 'text': 'Aunque el arquetipo se esconde hoy, tu singularidad resuena.', 'recommendation': 'Sigue explorando Senti.', 'icon': 'Award'})
    # STORY: REFLEXIÓN DEL USUARIO
    generated_stories.append({
        'type': 'user_reflection', # Nuevo tipo para esta historia
        'title': 'Tu Eco Interior',
        'text': (
            f"Después de este viaje por tu universo sonoro, {user_display_name}, "
            "¿sientes que estas melodías y reflexiones resuenan con tu yo actual? "
            "Tu perspectiva es la nota final más importante en esta sinfonía personal."
        ),
        'icon': 'HeartHandshake' # Un icono que sugiera conexión o validación
    })
    # Story Outro
    generated_stories.append({
        'type': 'outro', 'title': 'La Sinfonía de Tu Ser',
        'text': 'Este Wrapped es una partitura de tu viaje interior. Que la música siga siendo tu aliada, tu voz y tu refugio. ¡Tu historia en Senti resuena con fuerza!',
        'icon': 'Headphones' # Corregido el espacio
    })

    if not generated_stories or len(generated_stories) <= 2 :
        generated_stories = [{'type': 'error_fallback', 'title': '¡Un Momento!', 'text': 'Estamos afinando los últimos acordes de tu Wrapped. Vuelve en breve.', 'icon': 'XCircle'}]

    print(f"generate_wrapped_view: Finalizado. Devolviendo {len(generated_stories)} historias para {user_display_name}")
    return Response({'stories': generated_stories}, status=status.HTTP_200_OK)
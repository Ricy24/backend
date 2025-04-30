# therapy/utils/r2_storage.py
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError
from django.conf import settings
import logging
import uuid
import os
# Añadir import para parsear URLs
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

def get_r2_client():
    """Inicializa y devuelve un cliente S3 configurado para R2."""
    # --- Tu código existente para get_r2_client ---
    try:
        session = boto3.session.Session()
        client = session.client(
            service_name='s3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            region_name=settings.AWS_S3_REGION_NAME, # 'auto'
            config=boto3.session.Config(signature_version=settings.AWS_S3_SIGNATURE_VERSION), # 's3v4'
        )
        # Verificar conexión (opcional pero útil)
        client.list_buckets() # Lanza excepción si las credenciales/endpoint son inválidos
        logger.info("Conexión con R2 establecida correctamente.")
        return client
    except (NoCredentialsError, ClientError, BotoCoreError) as e: # Capturar errores más específicos
        logger.error(f"Error al conectar con R2: {e}", exc_info=True)
        # Relanzar como un error de conexión genérico para no exponer detalles de Boto
        raise ConnectionError(f"No se pudo conectar al servicio de almacenamiento: {e}") from e
    except Exception as e:
        logger.error(f"Error inesperado al inicializar cliente R2: {e}", exc_info=True)
        raise ConnectionError(f"Error desconocido al conectar al servicio de almacenamiento: {e}") from e


def upload_file_to_r2(file_obj, bucket_name, object_name, content_type=None, acl=settings.CLOUDFLARE_R2_DEFAULT_ACL):
    """
    Sube un objeto de archivo a un bucket R2 y devuelve la URL base del objeto o None si falla.
    """
    # --- Tu código existente para upload_file_to_r2 ---
    try:
        client = get_r2_client() # Obtiene el cliente S3/R2
        extra_args = {'ACL': acl}
        if content_type:
            extra_args['ContentType'] = content_type

        # Usamos upload_fileobj para manejar archivos en memoria eficientemente
        client.upload_fileobj(
            file_obj,
            bucket_name,
            object_name,
            ExtraArgs=extra_args
        )
        logger.info(f"Archivo '{object_name}' subido exitosamente a R2 bucket '{bucket_name}'.")

        # Devolver la URL base (endpoint + bucket + object_key)
        # Esta URL NO será directamente accesible si el objeto es privado.
        # Necesitaremos generar una URL prefirmada para el acceso.
        # Es importante guardar esta URL base para poder generar la prefirmada después.
        # Asegurarse de que no haya doble slash si el endpoint ya termina con uno
        base_endpoint = settings.AWS_S3_ENDPOINT_URL.rstrip('/')
        object_url = f"{base_endpoint}/{bucket_name}/{object_name}"

        return object_url

    except (ClientError, ConnectionError) as e: # Captura errores de cliente y conexión
        logger.error(f"Error al subir archivo a R2 '{object_name}': {e}", exc_info=True)
        return None
    except Exception as e: # Captura cualquier otro error inesperado
        logger.error(f"Error inesperado al subir archivo a R2 '{object_name}': {e}", exc_info=True)
        return None


def generate_unique_object_name(user_id, challenge_id, original_filename):
    """Genera un nombre de objeto único y estructurado para R2."""
    # --- Tu código existente para generate_unique_object_name ---
    try:
        # Extraer extensión del archivo original de forma segura
        _name, ext = os.path.splitext(original_filename)
        ext = ext.lower() if ext else '' # Asegurarse de que sea minúscula y exista
        # Crear un nombre único usando UUID
        unique_filename = f"{uuid.uuid4()}{ext}"
        # Estructura de carpeta recomendada (asegurar que los IDs sean strings si no lo son)
        return f"users/{str(user_id)}/challenges/{str(challenge_id)}/{unique_filename}"
    except Exception as e:
        logger.error(f"Error generando nombre único para '{original_filename}': {e}", exc_info=True)
        # Fallback a un nombre menos estructurado pero único
        return f"uploads/{uuid.uuid4()}"


# ============================================
# --- NUEVAS FUNCIONES AÑADIDAS ---
# ============================================

def get_object_key_from_url(file_url):
    """
    Extrae la clave del objeto (ruta/nombre) de una URL de R2/S3.
    Intenta manejar URLs con y sin el nombre del bucket en la ruta.
    """
    if not file_url or not isinstance(file_url, str):
        logger.warning("Se intentó extraer la clave de una URL inválida o no string.")
        return None
    try:
        parsed_url = urlparse(file_url)
        path = parsed_url.path.strip('/')

        # Eliminar el nombre del bucket si está al principio de la ruta
        # Compara con el nombre del bucket desde settings
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        if bucket_name and path.startswith(bucket_name + '/'):
             # Quita el nombre del bucket y el slash siguiente
             object_key = path[len(bucket_name) + 1:]
        else:
             # Asume que la ruta completa (sin slash inicial) es la clave
             object_key = path

        if not object_key: # Si después de quitar todo, queda vacío
            logger.warning(f"La clave del objeto extraída de '{file_url}' está vacía.")
            return None

        logger.debug(f"Clave extraída de '{file_url}': '{object_key}'")
        return object_key

    except Exception as e:
        logger.error(f"Error al parsear URL R2 '{file_url}' para obtener clave: {e}", exc_info=True)
        return None


def generate_presigned_url(bucket_name, object_key, expiration=3600):
    """
    Genera una URL prefirmada para acceder a un objeto privado en R2/S3.

    :param bucket_name: Nombre del bucket R2.
    :param object_key: Clave (ruta/nombre) del objeto dentro del bucket.
    :param expiration: Tiempo en segundos durante el cual la URL será válida (default: 1 hora).
    :return: La URL prefirmada como string, o None si hay error.
    """
    if not object_key:
        logger.warning("No se proporcionó object_key para generar URL prefirmada.")
        return None
    if not bucket_name:
         logger.error("Nombre del bucket no configurado (AWS_STORAGE_BUCKET_NAME). No se puede generar URL prefirmada.")
         return None

    try:
        r2_client = get_r2_client() # Obtener cliente configurado
        response = r2_client.generate_presigned_url(
            ClientMethod='get_object', # Método para obtener el objeto
            Params={'Bucket': bucket_name, 'Key': object_key},
            ExpiresIn=expiration, # Tiempo de validez
            HttpMethod='GET' # Método HTTP permitido para esta URL
         )
        logger.debug(f"URL prefirmada generada para '{object_key}' (expira en {expiration}s)")
        return response
    except (NoCredentialsError, ClientError, BotoCoreError, ConnectionError) as e: # Capturar errores comunes
        logger.error(f"Error al generar URL prefirmada para '{object_key}': {e}", exc_info=True)
        return None
    except Exception as e: # Capturar cualquier otro error
        logger.error(f"Error inesperado al generar URL prefirmada para '{object_key}': {e}", exc_info=True)
        return None
# ============================================
# --- FIN DE NUEVAS FUNCIONES ---
# ============================================
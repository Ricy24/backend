# therapy/signals.py
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.conf import settings
import logging
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from urllib.parse import urlparse

from .models import UserChallenge
# Importa la función get_r2_client si no la tienes en otro módulo de utils
# o define una versión simplificada aquí si es necesario.
# Asumiremos que está en utils.r2_storage por consistencia
from .utils.r2_storage import get_r2_client

logger = logging.getLogger(__name__)

def delete_r2_object(bucket_name, object_key):
    """Elimina un objeto específico de un bucket R2."""
    try:
        # Asegúrate de tener las credenciales configuradas en settings
        # y que get_r2_client funcione correctamente.
        r2 = get_r2_client()
        logger.info(f"Intentando eliminar objeto R2: Bucket='{bucket_name}', Key='{object_key}'")
        r2.delete_object(Bucket=bucket_name, Key=object_key)
        logger.info(f"Objeto R2 '{object_key}' eliminado exitosamente del bucket '{bucket_name}'.")
        return True
    except NoCredentialsError:
        logger.error("Error de credenciales al intentar eliminar objeto R2. Asegúrate de que las variables de entorno estén configuradas.", exc_info=False) # No mostrar traceback completo para credenciales
        return False
    except ClientError as e:
        # Manejar errores específicos como 'NoSuchKey' si ya no existe (opcional)
        if e.response['Error']['Code'] == 'NoSuchKey':
             logger.warning(f"El objeto R2 '{object_key}' no fue encontrado en el bucket '{bucket_name}'. Pudo haber sido eliminado previamente.")
             return True # Considerar como éxito si ya no existe
        else:
            logger.error(f"Error de Boto3 al eliminar objeto R2 '{object_key}': {e}", exc_info=True)
            return False
    except Exception as e:
        logger.error(f"Error inesperado al eliminar objeto R2 '{object_key}': {e}", exc_info=True)
        return False

def get_object_key_from_url(file_url):
    """Extrae la clave del objeto (ruta/nombre) de una URL de R2."""
    if not file_url:
        return None
    try:
        parsed_url = urlparse(file_url)
        # La clave es la ruta después del primer '/' (excluyendo el bucket si está en la ruta)
        # Asumiendo URL como: https://ACCOUNT_ID.r2.cloudflarestorage.com/BUCKET_NAME/path/to/file.jpg
        # O potencialmente: https://ACCOUNT_ID.r2.cloudflarestorage.com/path/to/file.jpg (si el bucket no está en path)
        path_parts = parsed_url.path.strip('/').split('/', 1)
        if len(path_parts) > 1 and path_parts[0] == settings.AWS_STORAGE_BUCKET_NAME:
             # Si el nombre del bucket está en la ruta, quitarlo
             return path_parts[1]
        elif len(path_parts) > 0:
             # Si el nombre del bucket no está en la ruta (común con endpoints R2)
             return parsed_url.path.strip('/')
        else:
            logger.warning(f"No se pudo extraer la clave del objeto R2 de la URL: {file_url}")
            return None
    except Exception as e:
        logger.error(f"Error al parsear la URL R2 '{file_url}': {e}", exc_info=True)
        return None


# Usar el decorador @receiver para conectar la función a la señal
@receiver(post_delete, sender=UserChallenge)
def delete_user_challenge_file(sender, instance, **kwargs):
    """
    Se ejecuta después de que un UserChallenge es eliminado.
    Busca un archivo asociado en R2 y lo elimina.
    """
    logger.debug(f"Señal post_delete recibida para UserChallenge ID: {instance.id}")

    # Verificar si el campo 'content' existe y es un diccionario
    if instance.content and isinstance(instance.content, dict):
        file_url = instance.content.get('file_url')
        storage_type = instance.content.get('storage')

        # Asegurarse de que la URL existe y que indica almacenamiento en R2
        if file_url and storage_type == 'r2':
            logger.info(f"UserChallenge {instance.id} eliminado tenía un archivo R2 asociado: {file_url}")

            # Extraer la clave del objeto (path dentro del bucket) de la URL
            object_key = get_object_key_from_url(file_url)

            if object_key:
                # Intentar eliminar el objeto del bucket R2
                delete_r2_object(settings.AWS_STORAGE_BUCKET_NAME, object_key)
            else:
                logger.warning(f"No se pudo determinar la clave del objeto R2 para eliminar desde la URL: {file_url}")
        else:
            logger.debug(f"UserChallenge {instance.id} eliminado no tenía archivo R2 válido en 'content'.")
    else:
         logger.debug(f"UserChallenge {instance.id} eliminado no tenía campo 'content' o no era un diccionario.")
from pathlib import Path
from datetime import timedelta
from decouple import config
from corsheaders.defaults import default_headers
import os



# Directorio base
BASE_DIR = Path(__file__).resolve().parent.parent

# Clave secreta y configuración básica
SECRET_KEY = config('SECRET_KEY', default='REMOVED_DJANGO_SECRET_KEY')
DEBUG = config('DEBUG', default=True, cast=bool)

# Modelo de usuario personalizado
AUTH_USER_MODEL = 'api.Usuario'

# URL del frontend
FRONTEND_URL = config('FRONTEND_URL', default='http://localhost:5174')

PUBLIC_BACKEND_URL = config('PUBLIC_BACKEND_URL', default='http://localhost:8000') 


ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    default='localhost,127.0.0.1', # Default solo para desarrollo si no hay .env
    cast=lambda v: [s.strip() for s in v.split(',')]
)


# Seguridad
CSRF_TRUSTED_ORIGINS = [
    "https://app.senti.lat",
    "https://senti.lat",
    "https://api.senti.lat",
]

# Configuración de CORS
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'api',
    'dashboard',
    'google_calendar',
    'therapy',
    'psychologist',
    'invitations',
    'community',
    'plant',
    'channels',
    'notifications',
    'pagos',
    'user_profile',
    'packages',
    'emails',
    'chat',
    'multiselectfield',
]

SITE_ID = 1

# Middleware
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
]

ROOT_URLCONF = 'backend.urls'

# Configuración de plantillas
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'

# Configuración de la base de datos (PostgreSQL)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='psicologia'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='REMOVED_DB_PASSWORD'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# Validadores de contraseñas
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Configuración de internacionalización y zona horaria
LANGUAGE_CODE = 'es'  # Español, adecuado para Colombia
TIME_ZONE = 'America/Bogota'  # Zona horaria de Bogotá (UTC-5)
USE_I18N = True  # Habilitado para internacionalización
USE_TZ = True  # Habilitado para manejo de zonas horarias
USE_L10N = True  # Habilitado para localización de formatos

# Archivos estáticos
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Archivos multimedia
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Configuración de REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DATETIME_FORMAT': "%Y-%m-%d %H:%M:%S",
    'DATETIME_INPUT_FORMATS': [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    ],
}

# Encabezados permitidos
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# Métodos permitidos
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# Configuración de CORS
CORS_ALLOWED_ORIGINS = [
    "https://sentifront-eight.vercel.app",  # Frontend en producción
]

CORS_ALLOW_CREDENTIALS = True  # Necesario para enviar cookies y tokens con credenciales
CORS_ALLOW_ALL_ORIGINS = False  # Evita el uso de comodín (*)




# Motor de sesiones
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Backends de autenticación
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
)

# Configuración de allauth
ACCOUNT_EMAIL_VERIFICATION = 'none'
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False

# Configuración de Simple JWT
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
}

# Configuración de Google Social Login y Calendar
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': [
            'profile',
            'email',
            'https://www.googleapis.com/auth/calendar',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        },
        'APP': {
            # El Client ID es público, puede tener un default
            'client_id': config('GOOGLE_CLIENT_ID', default='93294776142-if5ocrri0386a0ucmjjmkrnif7m6e7ng.apps.googleusercontent.com'),
            # ¡El Secret NUNCA debe tener default!
            'secret': config('GOOGLE_SECRET'),
            'key': config('GOOGLE_KEY', default='') # Si usas una API key específica también
        }
    }
}

# Configuración de reCAPTCHA
RECAPTCHA_PUBLIC_KEY = '6LcFlPAqAAAAAM7CSAxQRFNUN_wzmjNHmK3JyIHQ'
RECAPTCHA_PRIVATE_KEY = 'REMOVED_RECAPTCHA_PRIVATE_KEY'
RECAPTCHA_REQUIRED_SCORE = 0.5

# Configuración de seguridad (ajustada para desarrollo local)
# Configuración de seguridad
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)  # Forzar HTTPS en producción
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=True, cast=bool)  # Cookies solo por HTTPS
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=True, cast=bool)  # CSRF solo por HTTPS
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=3600, cast=int)  # HSTS para HTTPS
SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True, cast=bool)
SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=True, cast=bool)

# Claves API para servicios externos
GROQ_API_KEY = config('GROQ_API_KEY')
HUGGINGFACE_API_KEY = config('HUGGINGFACE_API_KEY')

# Configuración de logging (para depuración)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        '': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}

ASGI_APPLICATION = 'backend.asgi.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('127.0.0.1', 6379)],
        },
    },
}

CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_BEAT_SCHEDULE = {
    'check-upcoming-meetings-every-minute': {
        'task': 'notifications.tasks.check_upcoming_meetings',
        'schedule': 60.0,
    },
}

# Credenciales de PayU
PAYU_API_KEY = config('PAYU_API_KEY')
PAYU_API_LOGIN = config('PAYU_API_LOGIN')
PAYU_PUBLIC_KEY = config('PAYU_PUBLIC_KEY')
PAYU_MERCHANT_ID = config('PAYU_MERCHANT_ID')
PAYU_ACCOUNT_ID = config('PAYU_ACCOUNT_ID')
PAYU_TEST = config('PAYU_TEST', default=True, cast=bool)

# Configuración para Jitsi JWT
JITSI_JWT_SECRET = os.environ.get('JITSI_JWT_SECRET', 'REMOVED_JITSI_SECRET')
JITSI_JWT_ISSUER = 'django-app'
JITSI_JWT_AUDIENCE = 'jitsi'
JITSI_JWT_ALGORITHM = 'HS256'
JITSI_JWT_EXP_DELTA_SECONDS = timedelta(hours=2).total_seconds()
JITSI_DOMAIN = 'meet.jitsi'

# Credenciales Mercado Pago
MP_PUBLIC_KEY = config('MP_PUBLIC_KEY', default='')
MP_ACCESS_TOKEN = config('MP_ACCESS_TOKEN', default='')
ACTIVE_PAYMENT_PROVIDER = config('ACTIVE_PAYMENT_PROVIDER', default='PAYU')

# Configuración de email (SMTP para Gmail)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.zoho.com'
#EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'no-reply@senti.lat'
#EMAIL_HOST_USER = 'sentinfo.com@gmail.com'
#EMAIL_HOST_PASSWORD = 'REMOVED_EMAIL_APP_PASSWORD'
#DEFAULT_FROM_EMAIL = 'tu_correo@gmail.com'
DEFAULT_FROM_EMAIL = f"SentiBien <{EMAIL_HOST_USER}>"
# 5. No usar SSL explícito (ya que usamos TLS en el puerto 587)
EMAIL_USE_SSL = False
EMAIL_HOST_PASSWORD = config('ZOHO_EMAIL_PASSWORD')


# Configuración de WhiteNoise para archivos estáticos
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Configuración de Brevo
BREVO_API_KEY = config('BREVO_API_KEY')

SUPPORT_EMAIL = 'sentinfo@gmail.com'    # Cambia esto por el email de soporte real
SUPPORT_PHONE = '+57 3239219404'  # Cambia esto por el número de soporte real


#jetsit meet provecional
# settings.py
JITSI_MEET_BASE_URL = 'https://meet.jit.si'  # URL del servidor público de Jitsi Meet


# Directorio para archivos subidos
FILES_ROOT = os.path.join(BASE_DIR, 'uploads')
FILES_URL = '/uploads/'





# ==============================================================================
# CLOUDFLARE R2 / S3 STORAGE SETTINGS (Usando decouple)
# ==============================================================================
# Obtiene las credenciales y configuración desde las variables de entorno vía decouple

# Lee las variables específicas de Cloudflare R2
# No ponemos 'default' para las claves/secrets/account_id/bucket para forzar que estén en .env
CLOUDFLARE_R2_ACCOUNT_ID = config('CLOUDFLARE_R2_ACCOUNT_ID', default=None)
CLOUDFLARE_R2_ACCESS_KEY_ID = config('CLOUDFLARE_R2_ACCESS_KEY_ID', default=None)
CLOUDFLARE_R2_SECRET_ACCESS_KEY = config('CLOUDFLARE_R2_SECRET_ACCESS_KEY', default=None)
CLOUDFLARE_R2_BUCKET_NAME = config('CLOUDFLARE_R2_BUCKET_NAME', default=None)

# Construye el Endpoint URL
CLOUDFLARE_R2_ENDPOINT_URL = None
if CLOUDFLARE_R2_ACCOUNT_ID:
    CLOUDFLARE_R2_ENDPOINT_URL = f'https://{CLOUDFLARE_R2_ACCOUNT_ID}.r2.cloudflarestorage.com'
else:
    # Puedes mantener el print o usar logging si prefieres
    print("¡ADVERTENCIA! La variable de entorno CLOUDFLARE_R2_ACCOUNT_ID no está definida en .env o el entorno. R2 no funcionará correctamente.")

# --- Mapeo a las variables estándar de Boto3/Django-Storages ---
# Usamos las variables leídas arriba
AWS_ACCESS_KEY_ID = CLOUDFLARE_R2_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY = CLOUDFLARE_R2_SECRET_ACCESS_KEY
AWS_STORAGE_BUCKET_NAME = CLOUDFLARE_R2_BUCKET_NAME
AWS_S3_ENDPOINT_URL = CLOUDFLARE_R2_ENDPOINT_URL
AWS_S3_REGION_NAME = 'auto'  # Cloudflare R2 usa 'auto'
AWS_S3_SIGNATURE_VERSION = 's3v4'
AWS_S3_FILE_OVERWRITE = False # No sobrescribir archivos por defecto
AWS_DEFAULT_ACL = None # R2 no usa ACLs de la misma forma que S3. Se maneja en la subida.
AWS_QUERYSTRING_AUTH = True # Habilitar URLs prefirmadas (útil si los archivos son privados)

# --- Configuración específica de tu app (leída desde el entorno) ---
# 'private' es un buen default si no quieres que los archivos sean públicos
CLOUDFLARE_R2_DEFAULT_ACL = config('CLOUDFLARE_R2_DEFAULT_ACL', default='private')


# --- Verificación Opcional (usando las variables leídas) ---
# (Descomenta si quieres que la app falle al inicio si faltan credenciales)
# from django.core.exceptions import ImproperlyConfigured
#
# if not AWS_ACCESS_KEY_ID:
#     raise ImproperlyConfigured("La variable de entorno CLOUDFLARE_R2_ACCESS_KEY_ID no está configurada.")
# if not AWS_SECRET_ACCESS_KEY:
#     raise ImproperlyConfigured("La variable de entorno CLOUDFLARE_R2_SECRET_ACCESS_KEY no está configurada.")
# if not AWS_STORAGE_BUCKET_NAME:
#     raise ImproperlyConfigured("La variable de entorno CLOUDFLARE_R2_BUCKET_NAME no está configurada.")
# if not AWS_S3_ENDPOINT_URL:
#      raise ImproperlyConfigured("La variable de entorno CLOUDFLARE_R2_ACCOUNT_ID es necesaria y no está configurada.")


# ==============================================================================
# Fin de la configuración R2
# ==============================================================================z
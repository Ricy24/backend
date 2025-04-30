import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# Configura el entorno antes de cualquier importación que dependa de modelos
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()  # Inicializa Django para cargar las aplicaciones

# Ahora importa las cosas que dependen de modelos
from notifications.middleware import JWTAuthMiddleware
import notifications.routing

# Define la aplicación ASGI
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": JWTAuthMiddleware(
        AuthMiddlewareStack(
            URLRouter(
                notifications.routing.websocket_urlpatterns
            )
        )
    ),
})
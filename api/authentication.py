# api/authentication.py
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from firebase_admin import auth
from api.models import Usuario
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser

class FirebaseUser:
    def __init__(self, uid, email, nombre):
        self.uid = uid
        self.email = email
        self.nombre = nombre
        self.is_authenticated = True  # DRF necesita esto
        self.is_anonymous = False

    def __str__(self):
        return self.email

class FirebaseAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header or "Bearer " not in auth_header:
            return None

        token = auth_header.split("Bearer ")[1]
        try:
            decoded_token = auth.verify_id_token(token)
            uid = decoded_token["uid"]
            email = decoded_token["email"]
            name = decoded_token.get("name", "")

            usuario, created = Usuario.objects.get_or_create(
                uid=uid,
                defaults={"email": email, "nombre": name}
            )
            if not created:
                usuario.email = email
                usuario.nombre = name
                usuario.ultima_sesion = timezone.now()
                usuario.save()

            firebase_user = FirebaseUser(uid=uid, email=email, nombre=name)
            return (firebase_user, None)
        except auth.InvalidIdTokenError:
            raise AuthenticationFailed("Token inválido")
        except auth.ExpiredIdTokenError:
            raise AuthenticationFailed("Token expirado")



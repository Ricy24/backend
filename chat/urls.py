# chat/urls.py - CORREGIDO
from django.urls import path
# Importar los nombres CORRECTOS de las vistas y la nueva vista para privados
from .views import (
    TerapiaMensajesGrupalesView,
    EnviarMensajeTerapiaView,
    TerapiaMensajesPrivadosView, # <--- Añadir esta importación
    EliminarMensajeTerapiaView
)

app_name = 'chat'

urlpatterns = [
    # URL para mensajes GRUPALES
    path('terapia/<int:terapia_id>/mensajes/grupales/', TerapiaMensajesGrupalesView.as_view(), name='terapia-mensajes-grupales'),

    # URL para ENVIAR mensajes (grupales o privados)
    path('terapia/<int:terapia_id>/enviar/', EnviarMensajeTerapiaView.as_view(), name='enviar-mensaje-terapia'),

    # URL para mensajes PRIVADOS
    path('terapia/<int:terapia_id>/mensajes/privados/<int:other_user_id>/', TerapiaMensajesPrivadosView.as_view(), name='terapia-mensajes-privados'),

    # URL para ELIMINAR mensajes (probablemente ya estaba bien, pero ajustamos el nombre)
    path('terapia/<int:terapia_id>/mensajes/<int:mensaje_id>/eliminar/', EliminarMensajeTerapiaView.as_view(), name='eliminar-mensaje-terapia'),
]
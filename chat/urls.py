# chat/urls.py (adiciones)
from django.urls import path
from .views import (
    # ... (tus vistas de terapia existentes) ...
    ConfirmarSubMetaCoachingView,
    TerapiaMensajesGrupalesView,
    EnviarMensajeTerapiaView,
    TerapiaMensajesPrivadosView,
    EliminarMensajeTerapiaView,
    # Vistas de Coaching
    IniciarCoachingSessionView,
    CoachingSessionDetailView,
    EnviarMensajeCoachingView,
    CoachingMensajesListView,
    CoachingMetaListView,
    CoachingMetaDetailView,
)

app_name = 'chat' # o 'coaching' si lo haces una app separada

urlpatterns = [
    # --- URLs de Terapia (existentes) ---
    path('terapia/<int:terapia_id>/mensajes/grupales/', TerapiaMensajesGrupalesView.as_view(), name='terapia-mensajes-grupales'),
    path('terapia/<int:terapia_id>/enviar/', EnviarMensajeTerapiaView.as_view(), name='enviar-mensaje-terapia'),
    path('terapia/<int:terapia_id>/mensajes/privados/<int:other_user_id>/', TerapiaMensajesPrivadosView.as_view(), name='terapia-mensajes-privados'),
    path('terapia/<int:terapia_id>/mensajes/<int:mensaje_id>/eliminar/', EliminarMensajeTerapiaView.as_view(), name='eliminar-mensaje-terapia'),

    # --- URLs de Coaching con IA ---
    # Sesión de Coaching
    path('coaching/sesion/iniciar/', IniciarCoachingSessionView.as_view(), name='coaching-sesion-iniciar'),
    path('coaching/sesion/', CoachingSessionDetailView.as_view(), name='coaching-sesion-detalle'), # GET, PUT, DELETE para la sesión del usuario actual
    path('coaching/submeta/confirmar/', ConfirmarSubMetaCoachingView.as_view(), name='coaching-submeta-confirmar'),
    # Mensajes de Coaching
    path('coaching/mensajes/enviar/', EnviarMensajeCoachingView.as_view(), name='coaching-mensaje-enviar'),
    path('coaching/mensajes/', CoachingMensajesListView.as_view(), name='coaching-mensajes-lista'),

    # Metas de Coaching (opcional)
    path('coaching/metas/', CoachingMetaListView.as_view(), name='coaching-metas-lista'), # GET, POST
    path('coaching/metas/<int:meta_id>/', CoachingMetaDetailView.as_view(), name='coaching-meta-detalle'), # GET, PUT, DELETE


]
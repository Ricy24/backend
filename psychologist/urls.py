# psychologist/urls.py
from django.urls import path
from . import views
from .views import (
    GetMyPsychologistProfileView, UpdateMyPsychologistProfileView,
    SpecialtyListView, LanguageListView, MyPatientsListView,
    GetPsychologistPublicDetailView, MyAvailabilityListView, # Asegúrate que MyAvailabilityListView esté importada
    GetPsychologistAvailabilityView # Para la búsqueda general de usuarios
)

# --- Rutas para el PSICÓLOGO AUTENTICADO (Gestión propia) ---
# Prefijo asumido en urls.py principal: /api/psychologist/
urlpatterns_authenticated = [
    path('profile/me/', views.GetMyPsychologistProfileView.as_view(), name='my_profile'),
    path('profile/update/', views.UpdateMyPsychologistProfileView.as_view(), name='update_my_profile'),
    path('my-patients/', views.MyPatientsListView.as_view(), name='my_patients'),
    path('session/<str:event_id>/completed-challenges/', views.PatientSessionChallengesView.as_view(), name='patient_session_challenges'),
    # --- Gestión de MI disponibilidad ---
    path('availability/list/', views.MyAvailabilityListView.as_view(), name='my_availability_list'), # Ruta para GET (listar mi disponibilidad)
    path('availability/create/', views.create_psychologist_availability, name='create_my_availability'), # Ruta para POST (crear)
    path('availability/<int:availability_id>/update/', views.update_psychologist_availability, name='update_my_availability'), # Ruta para PUT/PATCH (actualizar)
    path('availability/<int:availability_id>/delete/', views.delete_psychologist_availability, name='delete_my_availability'), # Ruta para DELETE (eliminar)
]

# --- Rutas PÚBLICAS (Accesibles sin autenticación o por otros usuarios) ---
# Prefijo asumido en urls.py principal: /api/psychologist/
urlpatterns_public = [
    path('list/', views.get_psychologists, name='public_psychologist_list'), # Lista pública general de psicólogos
    path('<int:pk>/public-details/', views.GetPsychologistPublicDetailView.as_view(), name='public_psychologist_detail'), # Detalles públicos de UN psicólogo
    path('<int:psychologist_id>/availability/', views.get_psychologist_availability, name='public_psychologist_availability'), # Disponibilidad pública de UN psicólogo (quizás obsoleto si tienes la general)

    # --- Ruta para que usuarios busquen disponibilidad general ---
    # Nota: A veces se pone en una app diferente (ej. 'scheduling')
    path('availability/general/', views.GetPsychologistAvailabilityView.as_view(), name='public_psychologist_availability_search'),
]

# --- Rutas para Opciones (Especialidades, Idiomas) ---
# Prefijo asumido en urls.py principal: /api/options/ (o /api/psychologist/options/ si prefieres)
# ¡ASEGÚRATE DE INCLUIRLAS CORRECTAMENTE EN EL urls.py PRINCIPAL!
urlpatterns_options = [
     path('specialties/', views.SpecialtyListView.as_view(), name='options_specialties'),
     path('languages/', views.LanguageListView.as_view(), name='options_languages'),
]


# Combina las URLs que pertenecen a esta app 'psychologist'
# Decide si las opciones van aquí o en otro lugar
# Si incluyes esto como 'psychologist.urls', estas son las rutas relativas
urlpatterns = urlpatterns_authenticated + urlpatterns_public
# Podrías añadir urlpatterns_options aquí si quieres agruparlas,
# pero asegúrate que el prefijo en el urls.py principal sea correcto.
# Ejemplo: path('api/psychologist/options/', include(urlpatterns_options)) NO FUNCIONARÍA
# Deberías incluirlas directamente en el urls.py principal o en una app 'options'.
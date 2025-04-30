# user_profile/urls.py

from django.urls import path
from . import views # Importa las vistas desde el views.py de esta app

urlpatterns = [
    # Mantenemos los nombres originales para compatibilidad si es posible
    path('public/<int:user_id>/', views.PublicProfileView.as_view(), name='public_profile'),
    path('private/', views.PrivateProfileView.as_view(), name='private_profile'),

    # Puedes añadir más URLs específicas del perfil de usuario aquí en el futuro
]
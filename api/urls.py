from django.urls import path
from . import views
from .views import UserView, GetPsychologistAvailabilityView, ScheduleFreeSessionView, PsychologistRegisterView

from psychologist.views import SpecialtyListView, LanguageListView

urlpatterns = [
    # Authentication and user management
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('psychologist-register/', PsychologistRegisterView.as_view(), name='psychologist_register'), 
    path('users/', UserView.as_view(), name='user-profile'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('google-login/', views.GoogleLogin.as_view(), name='google_login'),
    path('register/', views.RegisterView.as_view(), name='register'),
    
    # User profile and settings
    path('users/update/', views.UpdateProfileView.as_view(), name='update_profile'),
    path('update-password/', views.UpdatePasswordView.as_view(), name='update_password'),
    path('update-notifications/', views.UpdateNotificationPrefsView.as_view(), name='update_notifications'),
    path('delete-account/', views.DeleteAccountView.as_view(), name='delete_account'),
    path('user-info/', views.user_info, name='user_info'),
    
    # Therapy and assessment
    path('initial-assessment/', views.SubmitInitialAssessmentView.as_view(), name='submit_initial_assessment'),
    path('psychologist-availability/', views.GetPsychologistAvailabilityView.as_view(), name='psychologist-availability'),
    path('schedule-free-session/', views.ScheduleFreeSessionView.as_view(), name='schedule-free-session'),

    # Therapy endpoints
    path('terapia/crear/', views.CrearTerapiaView.as_view(), name='crear_terapia'),
    path('terapias/', views.ListarTerapiasView.as_view(), name='listar_terapias'),
    path('terapia/<int:terapia_id>/', views.DetalleTerapiaView.as_view(), name='detalle_terapia'),

    # Resources and goals
    path('dashboard/', views.get_dashboard_data, name='dashboard_data'),
    path('personalized-resources/', views.get_personalized_resources, name='personalized_resources'),
    path('all-resources/', views.get_all_resources, name='all_resources'),
    path('create-resource/', views.create_resource, name='create_resource'),
    path('create-goal/', views.CreateWellnessGoalView.as_view(), name='create_wellness_goal'),
    path('goals/', views.UpdateGoalProgressView.as_view(), name='update_goal_progress'),
    
    # Options
    path('options/specialties/', SpecialtyListView.as_view(), name='options_specialties'),
    path('options/languages/', LanguageListView.as_view(), name='options_languages'),
]
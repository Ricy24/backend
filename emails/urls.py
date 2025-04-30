# emails/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('welcome/', views.SendWelcomeEmailView.as_view(), name='send_welcome_email'),
    path('password-reset/request/', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
]
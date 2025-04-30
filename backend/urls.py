# backend/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from emails import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include([
        path('', include('api.urls')),
        path('', include('plant.urls')),
    ])),
    path('api-auth/', include('rest_framework.urls')),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('accounts/', include('allauth.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('calendar/', include('google_calendar.urls')),
    # path('therapy/', include('therapy.urls')), # <-- LÍNEA ORIGINAL
    path('therapy/', include(('therapy.urls', 'therapy'), namespace='therapy')), # <-- LÍNEA CORREGIDA
    path('api/psychologist/', include('psychologist.urls')),
    path('api/invitations/', include('invitations.urls')),
    path('api/comunidad/', include('community.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/pagos/', include('pagos.urls')),
    path('api/profile/', include('user_profile.urls')),
    path('api/packages/', include('packages.urls')),
    path('chat/', include('chat.urls')),
    path('api/emails/welcome/', views.SendWelcomeEmailView.as_view(), name='send_welcome_email'),
    path('api/emails/password-reset/request/', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('api/emails/password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
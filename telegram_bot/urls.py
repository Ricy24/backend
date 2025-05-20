from django.urls import path
from .views import TelegramWebhookView 
from django.views.decorators.csrf import csrf_exempt  

app_name = 'telegram_bot'

urlpatterns = [
    # Ruta vacía, porque la base ya fue consumida por backend/urls.py
    path('', TelegramWebhookView.as_view(), name='webhook'),
]
# your_project/routing.py
from django.urls import re_path
from dashboard import consumers

websocket_urlpatterns = [
    re_path(r'ws/mood/$', consumers.MoodConsumer.as_asgi()),
]
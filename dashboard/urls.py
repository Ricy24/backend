from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_data, name='dashboard_data'),
    path('mood/', views.update_mood, name='update_mood'),
    path('diary/', views.create_diary_entry, name='create_diary_entry'),
    path('sleep/', views.log_sleep, name='log_sleep'),
    path('diary-entries/', views.diary_entries, name='diary_entries'),
    path('diary/talk/', views.talk_about_entry, name='talk_about_entry'),
    path('diary/export-day/<str:date_str>/', views.export_day_pdf, name='export_day_pdf'),
    path('diary/transcribe/', views.transcribe_audio_view, name='transcribe_audio'),
]
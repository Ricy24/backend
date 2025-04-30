from django.urls import path
from google_calendar.views import (
    CalendarEventCreateView, 
    CalendarEventListView,
    CalendarEventUpdateView,
    CalendarEventDeleteView,
    CalendarEventJitsiLinkView  # Nueva vista
)
from psychologist.views import GetPsychologistAvailabilityView

urlpatterns = [
    path('events/', CalendarEventListView.as_view(), name='calendar-events'),
    path('events/create/', CalendarEventCreateView.as_view(), name='calendar-event-create'),
    path('events/<str:event_id>/update/', CalendarEventUpdateView.as_view(), name='calendar-event-update'),
    path('events/<str:event_id>/delete/', CalendarEventDeleteView.as_view(), name='calendar-event-delete'),
    path('events/<str:event_id>/jitsi-link/', CalendarEventJitsiLinkView.as_view(), name='calendar-event-jitsi-link'),  # Nueva ruta
    path('psychologist/availability/', GetPsychologistAvailabilityView.as_view(), name='psychologist-availability'),
]
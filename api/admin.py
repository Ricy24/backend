# api/admin.py
from django.contrib import admin
from .models import Usuario, Terapia, MiembroTerapia, InvitacionTerapia, InitialAssessment, WellnessGoal, Resource


admin.site.register(Usuario)
admin.site.register(Terapia)
admin.site.register(MiembroTerapia)
admin.site.register(InvitacionTerapia)
admin.site.register(InitialAssessment)
admin.site.register(WellnessGoal)
admin.site.register(Resource)

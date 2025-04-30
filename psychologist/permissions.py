from rest_framework.permissions import BasePermission

class IsPsychologist(BasePermission):
    def has_permission(self, request, view):
        # Verifica si el usuario es staff o tiene un rol específico de psicóloga
        return request.user.is_authenticated and (request.user.is_staff or getattr(request.user, 'is_psychologist', False)) 
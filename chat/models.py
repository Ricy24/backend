# chat/models.py
from django.conf import settings
from api.models import Terapia, Usuario # Asegúrate que la importación de Terapia sea correcta
# from api.models import Usuario # No necesitas importar Usuario aquí si usas settings.AUTH_USER_MODEL
from django.db import models


class ChatConfig(models.Model):
    terapia = models.OneToOneField(
        Terapia,
        on_delete=models.CASCADE,
        related_name='chat_config'
    )
    chat_habilitado = models.BooleanField(default=True) # Cambiado a True por defecto (opcional)

    def __str__(self):
        return f"ChatConfig para Terapia {self.terapia.id} - Habilitado: {self.chat_habilitado}"

class Mensaje(models.Model):
    terapia = models.ForeignKey(
        Terapia,
        on_delete=models.CASCADE,
        related_name='mensajes_terapia' # Cambiado related_name para evitar conflicto
    )
    usuario = models.ForeignKey( # El que envía
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mensajes_enviados' # Cambiado related_name
    )
    # NUEVO CAMPO: Destinatario para mensajes privados
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, # Si el destinatario se borra, el mensaje queda sin destinatario explícito
        null=True,                 # Permite mensajes grupales (NULL)
        blank=True,                # Permite NULL en el admin y formularios
        related_name='mensajes_privados_recibidos' # Nuevo related_name
    )
    contenido = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['terapia', 'timestamp']),
            models.Index(fields=['terapia', 'recipient', 'timestamp']), # Índice para chats privados
        ]

    def __str__(self):
        if self.recipient:
            return f"Privado ({self.terapia.id}): {self.usuario.email} -> {self.recipient.email}: {self.contenido[:30]}"
        else:
            return f"Grupal ({self.terapia.id}): {self.usuario.email}: {self.contenido[:30]}"
        
class CoachingSession(models.Model):
    """Representa una sesión de coaching activa para un usuario."""
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='coaching_session'
    )
    objetivo_principal = models.TextField(
        help_text="El objetivo principal que el usuario quiere alcanzar con este coaching."
    )
    # Podrías añadir un campo para el 'estado' (activo, pausado, completado)
    # o para la 'metodología' de coaching si quieres ser más específico.
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True)
    # Memoria de conversación para Groq (resumen o puntos clave)
    # Esto podría ser un JSONField si usas PostgreSQL, o un TextField
    # donde almacenes un resumen o estado que se pasa a Groq.
    # Por ahora, construiremos la memoria a partir de los mensajes.

    def __str__(self):
        return f"Coaching para {self.usuario.email} - Objetivo: {self.objetivo_principal[:50]}..."

class CoachingMensaje(models.Model):
    """Mensajes intercambiados durante una sesión de coaching."""
    sesion = models.ForeignKey(
        CoachingSession,
        on_delete=models.CASCADE,
        related_name='mensajes_coaching'
    )
    # Quién envía: el usuario o la IA.
    # Podríamos tener un campo 'emisor' (usuario, ia) o un booleano
    es_respuesta_ia = models.BooleanField(default=False)
    contenido = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    # Campo opcional para datos adicionales de la IA (e.g., intenciones, análisis)
    # metadata_ia = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['sesion', 'timestamp']),
        ]

    def __str__(self):
        emisor = "IA Coach" if self.es_respuesta_ia else self.sesion.usuario.email
        return f"Coaching ({self.sesion.id}): {emisor}: {self.contenido[:50]}"

# Opcional: Modelo para Sub-Metas o Pasos
class CoachingMeta(models.Model):
    sesion = models.ForeignKey(
        CoachingSession,
        on_delete=models.CASCADE,
        related_name='metas_coaching'
    )
    descripcion = models.CharField(max_length=255)
    completada = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_limite = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Meta para {self.sesion.usuario.email}: {self.descripcion}"
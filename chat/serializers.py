# chat/serializers.py
from rest_framework import serializers
from .models import Mensaje
from django.contrib.auth import get_user_model # Mejor forma de obtener User

Usuario = get_user_model()

class MensajeSerializer(serializers.ModelSerializer):
    # Quién envía el mensaje
    usuario_email = serializers.EmailField(source='usuario.email', read_only=True)
    nombre_usuario = serializers.CharField(source='usuario.nombre', read_only=True) # Asume que tu modelo User tiene 'nombre'

    # Quién recibe (si es privado)
    recipient_email = serializers.EmailField(source='recipient.email', read_only=True, allow_null=True)
    nombre_recipient = serializers.CharField(source='recipient.nombre', read_only=True, allow_null=True)

    # Campo para enviar el ID del destinatario (solo para escribir)
    recipient_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Mensaje
        fields = [
            'id',
            'terapia',          # ID de la terapia
            'usuario_email',    # Email del remitente
            'nombre_usuario',   # Nombre del remitente
            'recipient_id',     # ID del destinatario (para enviar privado)
            'recipient_email',  # Email del destinatario (solo lectura)
            'nombre_recipient', # Nombre del destinatario (solo lectura)
            'contenido',
            'timestamp'
        ]
        read_only_fields = [
            'id', 'terapia', 'usuario_email', 'nombre_usuario',
            'recipient_email', 'nombre_recipient', 'timestamp'
        ] # 'terapia' y 'usuario' se asignan en la vista

    # Opcional: Validar que el recipient_id existe y pertenece a la terapia
    def validate_recipient_id(self, value):
        if value is not None:
            try:
                # Obtener terapia_id del contexto (si se pasa desde la vista)
                terapia_id = self.context.get('terapia_id')
                if not terapia_id:
                    # O intentar obtenerlo del objeto si es una actualización (menos común para crear)
                    terapia_id = self.instance.terapia.id if self.instance else None

                if not terapia_id:
                     raise serializers.ValidationError("Contexto de terapia no encontrado para validar destinatario.")

                recipient = Usuario.objects.get(id=value)
                # Verificar si el destinatario es miembro de la terapia
                if not MiembroTerapia.objects.filter(terapia_id=terapia_id, usuario=recipient).exists():
                     raise serializers.ValidationError("El destinatario seleccionado no es miembro de esta terapia.")
                return value # Devuelve el ID validado
            except Usuario.DoesNotExist:
                raise serializers.ValidationError("Usuario destinatario no encontrado.")
        return None # Si es None (mensaje grupal), está bien
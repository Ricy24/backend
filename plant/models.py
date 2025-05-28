# plant/models.py
from django.db import models
from django.conf import settings # Import settings si usas AUTH_USER_MODEL
from django.utils import timezone
from django.db.models import F
from api.models import Terapia # Asegúrate de que la ruta es correcta
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)
User = settings.AUTH_USER_MODEL # Usar el modelo de usuario de settings

class Plant(models.Model):
    terapia = models.OneToOneField(
        'api.Terapia', # Usar string si api se importa después o hay dependencia circular
        on_delete=models.CASCADE,
        related_name='plant'
    )
    name = models.CharField(max_length=100, default="Mi Planta Compañera")
    type = models.CharField(max_length=20, choices=[('planta', 'Planta'), ('arbol', 'Árbol')], default='planta')
    design = models.CharField(max_length=100, default="default_plant")
    level = models.PositiveIntegerField(default=1)
    current_streak = models.PositiveIntegerField(default=0)
    # Usa DateField, es más simple para comparar días
    last_care_date = models.DateField(null=True, blank=True, help_text="Último día (local) en que la planta recibió cuidados.")
    # El campo is_alive puede ser útil visualmente, pero no lo usaremos para calcular la racha
    is_alive = models.BooleanField(default=True, help_text="Indicador visual (actualizado por care).")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Podrías definir constantes para niveles si quieres
    # LEVEL_THRESHOLDS = { 1: 0, 2: 7, 3: 15, ... }

    def __str__(self):
        status = "Viva" if self.is_alive else "Necesita Cuidados"
        return f"{self.name} (N:{self.level} R:{self.current_streak}) T:{self.terapia_id} [{status}]"

    def care(self, caring_user: User):
        """
        Registra el cuidado de la planta para el día actual (local).
        Actualiza la racha, la fecha del último cuidado y el estado is_alive.
        Devuelve: (bool: success, str: message, dict: status)
        """
        # --- USA FECHA LOCAL ---
        today = timezone.localdate() # Obtiene la fecha local correcta (ej: America/Bogota)
        # -----------------------

        # Estado inicial para el diccionario de respuesta
        status_dict = {'level': self.level, 'streak': self.current_streak, 'is_alive': self.is_alive}

        # 1. Verificar si ya se cuidó hoy
        if self.last_care_date == today:
            message = f"{self.name} ya recibió cuidados hoy."
            logger.debug(f"Planta T:{self.terapia_id}: Intento de cuidado por {caring_user.email}, pero ya cuidada en {today}.")
            # Asegurarnos que is_alive esté True si se cuidó hoy
            if not self.is_alive:
                self.is_alive = True
                self.save(update_fields=['is_alive'])
                status_dict['is_alive'] = True # Actualizar dict de respuesta
            return False, message, status_dict

        # 2. Determinar la nueva racha y el mensaje
        new_streak = 0
        should_increment_streak = False
        just_revived = False

        if self.last_care_date:
            yesterday = today - timedelta(days=1)
            if self.last_care_date == yesterday:
                # Continuar racha
                should_increment_streak = True
                message = f"¡{self.name} agradece tus cuidados! Racha continúa."
                logger.info(f"Planta T:{self.terapia_id}: Cuidado hoy ({today}), racha continúa desde {self.last_care_date}.")
            else:
                # Racha rota (último cuidado fue antes de ayer o más lejos)
                new_streak = 1 # Reiniciar a 1 (cuidado de hoy)
                message = f"¡Bien hecho! Has iniciado una nueva racha para {self.name}."
                logger.info(f"Planta T:{self.terapia_id}: Cuidado hoy ({today}), racha rota (último: {self.last_care_date}). Iniciando nueva racha en 1.")
        else:
            # Primer cuidado
            new_streak = 1
            message = f"¡Has comenzado a cuidar a {self.name}!"
            logger.info(f"Planta T:{self.terapia_id}: Primer cuidado hoy ({today}). Iniciando racha en 1.")

        # 3. Actualizar los campos
        self.last_care_date = today
        self.is_alive = True # Siempre viva si se cuidó hoy
        if should_increment_streak:
             # Usar F() para evitar race conditions si múltiples llamadas ocurren casi al mismo tiempo
             # (aunque la lógica en therapy/views debería prevenirlo para el mismo día)
            self.current_streak = F('current_streak') + 1
        else:
            self.current_streak = new_streak # Asignar 0 o 1 según corresponda

        # --- Lógica de Nivel (Opcional, ejemplo simple) ---
        # self.level = ... basado en la nueva racha o un contador total
        # logger.info(f"Planta T:{self.terapia_id} subió al nivel {self.level}.")

        # 4. Guardar cambios
        update_fields = ['last_care_date', 'is_alive', 'current_streak']
        # if level_changed: update_fields.append('level')
        self.save(update_fields=update_fields)

        # 5. Refrescar para obtener el valor actualizado de F()
        # y cualquier otro campo que pudiera cambiar (como level)
        refresh_fields = ['current_streak', 'is_alive', 'level'] # Añadir 'level' si lo actualizas
        self.refresh_from_db(fields=refresh_fields)

        # 6. Preparar el diccionario de estado actualizado
        status_dict = {'level': self.level, 'streak': self.current_streak, 'is_alive': self.is_alive}

        # 7. Devolver éxito
        return True, message, status_dict

    # Eliminar el método check_liveness si ya no se usa externamente
    # def check_liveness(self, today=None): ...

    class Meta:
         verbose_name = "Planta de Terapia"
         verbose_name_plural = "Plantas de Terapia"
         ordering = ['terapia']

# --- ELIMINAR o COMENTAR el modelo CareAction si ya no se usa ---
# class CareAction(models.Model):
#     """Modelo que registra las acciones de cuidado diarias."""
#     plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='care_actions')
#     user = models.ForeignKey(User, on_delete=models.CASCADE)
#     action_date = models.DateField(auto_now_add=True) # Cambiado a auto_now_add para simplificar
#     action_type = models.CharField(max_length=50, default="cuidado_diario")
#
#     class Meta:
#         unique_together = ('plant', 'user', 'action_date')
#         indexes = [ models.Index(fields=['plant', 'action_date']), ] # Indexar para búsquedas rápidas
#
#     def __str__(self):
#         return f"Cuidado por {self.user.id} en {self.action_date}"

class PlantDesign(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nombre del diseño")
    design_key = models.CharField(max_length=100, unique=True, verbose_name="Clave del diseño")
    description = models.TextField(blank=True, verbose_name="Descripción")
    image_url = models.URLField(verbose_name="URL de la imagen")
    plant_type = models.CharField(
        max_length=20,
        choices=[('planta', 'Planta'), ('arbol', 'Árbol'), ('ambos', 'Ambos')],
        default='planta',
        verbose_name="Tipo de planta"
    )
    is_active = models.BooleanField(default=True, verbose_name="Activo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Diseño de Planta"
        verbose_name_plural = "Diseños de Plantas"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_plant_type_display()})"
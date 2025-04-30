from django.apps import AppConfig



class TherapyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'therapy'

    def ready(self):
        # Importa las señales aquí para que se registren al iniciar la app
        try:
            import therapy.signals
            print("Señales de Therapy cargadas.") # Mensaje de depuración
        except ImportError:
             print("Advertencia: No se pudo importar therapy.signals.")
             pass # Evita errores si el archivo no existe o tiene problemas
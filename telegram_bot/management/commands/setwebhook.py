# telegram_bot/management/commands/setwebhook.py

import requests
import json # Asegúrate de que esta línea esté si usas json.dumps en el --info
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand): # La clase se llama Command
    help = 'Configura el webhook de Telegram para el bot o muestra/elimina el actual'

    def add_arguments(self, parser): # Este método debe estar indentado DENTRO de la clase Command
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Elimina el webhook en lugar de configurarlo',
        )
        parser.add_argument(
            '--info',
            action='store_true',
            help='Muestra la información del webhook actual',
        )

    def handle(self, *args, **options): # <<<--- ESTE ES EL MÉTODO IMPORTANTE.
                                        #      Debe llamarse 'handle' y estar indentado
                                        #      DENTRO de la clase Command.
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stdout.write(self.style.ERROR("TELEGRAM_BOT_TOKEN no está configurado en settings."))
            return

        bot_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"

        if options['delete']:
            url = f"{bot_url}/deleteWebhook"
            try: # Envuelve las peticiones en try-except
                response = requests.get(url, timeout=10)
                response.raise_for_status() # Chequea errores HTTP
                if response.json().get("ok"):
                    self.stdout.write(self.style.SUCCESS(f"Webhook eliminado exitosamente: {response.json()}"))
                else:
                    self.stdout.write(self.style.ERROR(f"Error eliminando webhook: {response.status_code} - {response.text}"))
            except requests.exceptions.RequestException as e:
                self.stdout.write(self.style.ERROR(f"Error de red eliminando webhook: {e}"))
            return

        if options['info']:
            url = f"{bot_url}/getWebhookInfo"
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                if response.json().get("ok"):
                    # Usa json.dumps para formatear la salida
                    self.stdout.write(self.style.SUCCESS(f"Información del Webhook: {json.dumps(response.json(), indent=2)}"))
                else:
                    self.stdout.write(self.style.ERROR(f"Error obteniendo info del webhook: {response.status_code} - {response.text}"))
            except requests.exceptions.RequestException as e:
                self.stdout.write(self.style.ERROR(f"Error de red obteniendo info del webhook: {e}"))
            return

        # Establecer webhook (si no es --delete ni --info)
        if not settings.TELEGRAM_WEBHOOK_URL:
            self.stdout.write(self.style.ERROR("TELEGRAM_WEBHOOK_URL no está configurada en settings. Revisa PUBLIC_BACKEND_URL."))
            return

        set_webhook_url = f"{bot_url}/setWebhook"
        payload = {'url': settings.TELEGRAM_WEBHOOK_URL}

        # Opcional: si usas secret_token con la API de Telegram
        # if hasattr(settings, 'TELEGRAM_WEBHOOK_API_SECRET') and settings.TELEGRAM_WEBHOOK_API_SECRET:
        #     payload['secret_token'] = settings.TELEGRAM_WEBHOOK_API_SECRET

        try:
            response = requests.post(set_webhook_url, data=payload, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                self.stdout.write(self.style.SUCCESS(
                    f"Webhook configurado exitosamente a: {settings.TELEGRAM_WEBHOOK_URL}"
                ))
                self.stdout.write(self.style.SUCCESS(f"Respuesta de Telegram: {result}"))
            else:
                self.stdout.write(self.style.ERROR(
                    f"Error configurando webhook: {result.get('description', 'Error desconocido')}"
                ))
        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Error de red configurando webhook: {e}"))
        except Exception as e: # Captura genérica para otros errores
            self.stdout.write(self.style.ERROR(f"Error inesperado configurando webhook: {e}"))
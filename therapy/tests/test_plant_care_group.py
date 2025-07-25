# therapy/tests/test_plant_care_group.py

from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

# Importa tus modelos...
from api.models import Terapia, MiembroTerapia
from plant.models import Plant
from therapy.models import Challenge, UserChallenge, Category, UserPathProgress

# Importa la función para obtener tokens si la tienes, o créala si es necesario
# from rest_framework_simplejwt.tokens import RefreshToken # Ejemplo

User = get_user_model()

class GroupPlantCareTest(APITestCase):

    def setUp(self):
        self.user1 = User.objects.create_user(email='testpareja1@example.com', password='password123', nombre='Pareja Uno')
        self.user2 = User.objects.create_user(email='testpareja2@example.com', password='password123', nombre='Pareja Dos')
        self.terapia = Terapia.objects.create(tipo='pareja') # Corregido
        MiembroTerapia.objects.create(usuario=self.user1, terapia=self.terapia)
        MiembroTerapia.objects.create(usuario=self.user2, terapia=self.terapia)
        yesterday = timezone.localdate() - timedelta(days=1)
        self.plant = Plant.objects.create(
            terapia=self.terapia, name="Planta Grupal Test", design="default_plant",
            current_streak=5, last_care_date=yesterday
        )
        self.category = Category.objects.create(name="Comunicación Test")
        self.challenge = Challenge.objects.create(
            title="Reto Diario Test", description="Descripción del reto",
            category=self.category, level=1, type='activity', tools='text'
        )
        UserPathProgress.objects.create(user=self.user1, terapia=self.terapia, current_level=1)
        UserPathProgress.objects.create(user=self.user2, terapia=self.terapia, current_level=1)
        self.complete_challenge_url = reverse('therapy:user_challenges')
        self.today = timezone.localdate()


    def test_plant_care_after_all_members_complete(self):
        # ... (Crear UserChallenges 1 y 2 sin cambios) ...
        challenge1 = UserChallenge.objects.create(
            user=self.user1, terapia=self.terapia, challenge=self.challenge, available_date=self.today
        )
        challenge2 = UserChallenge.objects.create(
            user=self.user2, terapia=self.terapia, challenge=self.challenge, available_date=self.today
        )

        # --- Simular Usuario 1 completando ---
        # ***** CAMBIO: Forzar autenticación *****
        self.client.force_authenticate(user=self.user1)
        # self.client.login(email='testpareja1@example.com', password='password123') # Ya no es necesario login
        data_user1 = {
            'user_challenge_id': challenge1.id,
            'terapia_id': self.terapia.id,
            'text': 'Completado por usuario 1'
        }
        response1 = self.client.post(self.complete_challenge_url, data_user1, format='json')

        # Verificar status (debe ser 200 OK)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # ... (Verificaciones de planta y reto 1 sin cambios) ...
        self.plant.refresh_from_db()
        yesterday = timezone.localdate() - timedelta(days=1) # Recalcular por si acaso
        self.assertEqual(self.plant.last_care_date, yesterday) # Aún debe ser ayer
        self.assertEqual(self.plant.current_streak, 5)
        self.assertIn('plant_care_info', response1.data)
        self.assertEqual(response1.data['plant_care_info']['status'], 'pending_group')
        self.assertIn('Esperando', response1.data['plant_care_info']['message'])
        challenge1.refresh_from_db()
        self.assertTrue(challenge1.is_completed)

        # --- Simular Usuario 2 completando (el mismo día) ---
        # ***** CAMBIO: Forzar autenticación para user2 *****
        self.client.force_authenticate(user=self.user2)
        # self.client.logout() # Ya no es necesario
        # self.client.login(email='testpareja2@example.com', password='password123') # Ya no es necesario login
        data_user2 = {
            'user_challenge_id': challenge2.id,
            'terapia_id': self.terapia.id,
            'text': 'Completado por usuario 2'
        }
        response2 = self.client.post(self.complete_challenge_url, data_user2, format='json')

        # Verificar status (debe ser 200 OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # ... (Verificaciones de planta y reto 2 sin cambios) ...
        self.plant.refresh_from_db()
        self.assertEqual(self.plant.last_care_date, self.today) # Ahora debe ser hoy
        self.assertEqual(self.plant.current_streak, 6) # Racha incrementada
        self.assertIn('plant_care_info', response2.data)
        self.assertNotIn('status', response2.data['plant_care_info'])
        self.assertIn('Racha continúa', response2.data['plant_care_info']['message']) 
        self.assertEqual(response2.data['plant_care_info']['streak'], 6)
        challenge2.refresh_from_db()
        self.assertTrue(challenge2.is_completed)

        # ***** CAMBIO: Limpiar autenticación al final (buena práctica) *****
        self.client.force_authenticate(user=None)
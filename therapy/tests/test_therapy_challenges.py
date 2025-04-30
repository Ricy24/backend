from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from datetime import timedelta

# Asegúrate de importar tus modelos correctamente
from api.models import Terapia, MiembroTerapia
from ..models import (
    Category, Challenge, EmotionalPath, UserChallenge, UserPathProgress,
    EmotionalProfile # Necesario si la asignación depende de él
)

# Obtener el modelo de usuario
User = get_user_model()

class TherapyChallengeAPITests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        """Configuración inicial que se ejecuta una vez para la clase."""
        # --- Crear Usuarios ---
        cls.user = User.objects.create_user(
            email='testuser@example.com',
            password='password123',
            first_name='Test',
            last_name='User'
        )
        # Podrías necesitar un terapeuta si alguna lógica lo requiere
        # cls.therapist = User.objects.create_user(email='therapist@example.com', password='password123', is_staff=True)

        # --- Crear Terapia y Membresía ---
        cls.terapia = Terapia.objects.create(
            tipo='individual'  # Solo necesita el tipo, que es obligatorio
            # Quita la línea de nombre_terapia
        )
        MiembroTerapia.objects.create(terapia=cls.terapia, usuario=cls.user)

        # --- Crear Categorías y Retos ---
        cls.category_ansiedad = Category.objects.create(name='Ansiedad', description='Retos para la ansiedad')
        cls.category_autoestima = Category.objects.create(name='Autoestima', description='Retos para autoestima')

        # Retos Nivel 1
        cls.challenge_ansiedad_1 = Challenge.objects.create(
            category=cls.category_ansiedad,
            title='Respiración Profunda',
            description='Practica 5 minutos de respiración diafragmática.',
            level=1,
            tools='reflection',       # <-- Herramienta que dispara la validación
            reveal_after_days=1       # <-- CAMBIA A 1 (o cualquier número > 0)
        )
        cls.challenge_ansiedad_2 = Challenge.objects.create(
            category=cls.category_ansiedad,
            title='Observación Consciente',
            description='Describe 3 cosas que ves a tu alrededor.',
            level=1,
            tools='text'              # <-- No necesita reveal_after_days > 0
            # reveal_after_days=0    # (Opcional: Dejar el default 0 está bien aquí)
        )
        # Reto Nivel 1 - Otra Categoría
        cls.challenge_autoestima_1 = Challenge.objects.create(
            category=cls.category_autoestima,
            title='Logro del Día',
            description='Escribe algo que lograste hoy, por pequeño que sea.',
            level=1,
            tools='text'              # <-- No necesita reveal_after_days > 0
            # reveal_after_days=0    # (Opcional: Dejar el default 0 está bien aquí)
        )

        # --- Crear Perfil Emocional (Básico - ajusta si tu lógica es compleja) ---
        # Asume que EmotionalPathView.post necesita un perfil para saber qué rutas activar
        cls.profile = EmotionalProfile.objects.create(
            user=cls.user,
            terapia=cls.terapia,
            scores={'high_priority': ['Ansiedad'], 'moderate_priority': [], 'low_priority': ['Autoestima']}
        )

        # --- Crear Progreso del Usuario ---
        cls.progress = UserPathProgress.objects.create(
            user=cls.user,
            terapia=cls.terapia,
            current_level=1
        )

        # --- Crear Ruta Emocional Activa ---
        # Necesario para que se puedan asignar retos de esa categoría
        EmotionalPath.objects.create(
            user=cls.user,
            terapia=cls.terapia,
            category=cls.category_ansiedad,
            level=1,
            is_active=True
        )
        # Nota: No creamos ruta para Autoestima inicialmente para algunos tests

    def setUp(self):
        """Configuración que se ejecuta antes de CADA test."""
        # Autenticar al cliente para las pruebas de API
        self.client.force_authenticate(user=self.user)
        # Asegurarse de que no haya retos preexistentes de pruebas anteriores (aunque setUpTestData ayuda)
        # UserChallenge.objects.filter(user=self.user, terapia=self.terapia).delete()

    # --- Helper para obtener la fecha local ---
    def get_today_local_date(self):
        return timezone.localtime(timezone.now()).date()

    # =========================================
    # Pruebas de Asignación (EmotionalPathView)
    # =========================================
    def test_assign_daily_challenge_when_none_exists_for_today(self):
        """
        Verifica que se asigne un reto diario si no existe uno para hoy.
        Se asume que la primera llamada a EmotionalPathView lo activa.
        """
        today = self.get_today_local_date()
        # Verificar que no hay retos HOY antes de la llamada
        self.assertFalse(UserChallenge.objects.filter(user=self.user, terapia=self.terapia, available_date=today).exists())

        url = reverse('therapy:activate_paths') # Asegúrate que 'therapy:activate_paths' es el name= correcto en tus urls.py
        response = self.client.post(url, {'terapia_id': self.terapia.id}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['challenge_assigned_today'])
        # Verificar que AHORA SÍ hay un reto para hoy
        self.assertTrue(UserChallenge.objects.filter(user=self.user, terapia=self.terapia, available_date=today, is_completed=False).exists())
        # Verificar que solo se creó uno
        self.assertEqual(UserChallenge.objects.filter(user=self.user, terapia=self.terapia, available_date=today).count(), 1)
        # Verificar que el reto pertenece a la categoría activa (Ansiedad)
        uc = UserChallenge.objects.get(user=self.user, terapia=self.terapia, available_date=today)
        self.assertEqual(uc.challenge.category, self.category_ansiedad)

    def test_do_not_assign_challenge_if_one_exists_for_today(self):
        """Verifica que NO se asigne otro reto si ya existe uno para hoy."""
        today = self.get_today_local_date()
        # Crear manualmente un reto para hoy ANTES de la llamada
        existing_uc = UserChallenge.objects.create(
            user=self.user,
            terapia=self.terapia,
            challenge=self.challenge_ansiedad_1,
            available_date=today
        )

        url = reverse('therapy:activate_paths')
        response = self.client.post(url, {'terapia_id': self.terapia.id}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['challenge_assigned_today']) # No debió asignar uno nuevo
        # Verificar que sigue habiendo solo UN reto para hoy
        self.assertEqual(UserChallenge.objects.filter(user=self.user, terapia=self.terapia, available_date=today).count(), 1)
        # Verificar que el reto existente no fue modificado (su ID es el mismo)
        self.assertTrue(UserChallenge.objects.filter(id=existing_uc.id, available_date=today).exists())

    # =========================================
    # Pruebas de Obtención (UserChallengeView GET)
    # =========================================
    def test_get_pending_challenges_returns_daily_challenge(self):
        """Verifica que se devuelva el reto diario correcto cuando existe."""
        today = self.get_today_local_date()
        # Crear un reto para hoy
        uc_today = UserChallenge.objects.create(
            user=self.user,
            terapia=self.terapia,
            challenge=self.challenge_ansiedad_1,
            available_date=today
        )
        url = reverse('therapy:user_challenges') # Asegúrate que este es el name= correcto
        response = self.client.get(url, {'terapia_id': self.terapia.id, 'status': 'pending'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data['daily_challenge'])
        self.assertEqual(response.data['daily_challenge']['id'], uc_today.id)
        self.assertEqual(response.data['daily_challenge']['challenge']['id'], self.challenge_ansiedad_1.id)
        self.assertEqual(len(response.data['missed_challenges']), 0) # No hay retos perdidos

    def test_get_pending_challenges_returns_none_when_no_daily(self):
        """Verifica que daily_challenge sea null si no hay reto para hoy."""
        today = self.get_today_local_date()
        # Asegurarse que no hay retos para hoy
        UserChallenge.objects.filter(user=self.user, terapia=self.terapia, available_date=today).delete()

        url = reverse('therapy:user_challenges')
        response = self.client.get(url, {'terapia_id': self.terapia.id, 'status': 'pending'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['daily_challenge'])
        self.assertEqual(len(response.data['missed_challenges']), 0)

    def test_get_pending_challenges_returns_missed_challenges(self):
        """Verifica que se devuelvan los retos de días anteriores no completados."""
        today = self.get_today_local_date()
        yesterday = today - timedelta(days=1)
        day_before = today - timedelta(days=2)

        # Crear reto perdido de ayer
        uc_yesterday = UserChallenge.objects.create(
            user=self.user, terapia=self.terapia, challenge=self.challenge_ansiedad_1,
            available_date=yesterday, is_completed=False
        )
        # Crear reto COMPLETADO de anteayer (no debería aparecer como perdido)
        UserChallenge.objects.create(
            user=self.user, terapia=self.terapia, challenge=self.challenge_ansiedad_2,
            available_date=day_before, is_completed=True, completed_at=timezone.now()
        )
         # Crear reto para hoy (opcional, para ver ambos)
        uc_today = UserChallenge.objects.create(
            user=self.user, terapia=self.terapia, challenge=self.challenge_autoestima_1, # Usamos otro reto
            available_date=today, is_completed=False
        )
        # Activar ruta de Autoestima para que el reto de hoy sea válido (si no se hizo en setup)
        EmotionalPath.objects.get_or_create(
             user=self.user, terapia=self.terapia, category=self.category_autoestima,
             defaults={'level': 1, 'is_active': True}
        )


        url = reverse('therapy:user_challenges')
        response = self.client.get(url, {'terapia_id': self.terapia.id, 'status': 'pending'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verificar reto de hoy
        self.assertIsNotNone(response.data['daily_challenge'])
        self.assertEqual(response.data['daily_challenge']['id'], uc_today.id)
        # Verificar reto perdido
        self.assertEqual(len(response.data['missed_challenges']), 1)
        self.assertEqual(response.data['missed_challenges'][0]['id'], uc_yesterday.id)
        self.assertEqual(response.data['missed_challenges'][0]['challenge']['id'], self.challenge_ansiedad_1.id)

    # =========================================
    # Pruebas de Reemplazo (ReplaceDailyChallengeView)
    # =========================================
    def test_replace_daily_challenge_success(self):
        """Verifica que se pueda reemplazar el reto diario por otro disponible."""
        today = self.get_today_local_date()
        # Crear el reto original para hoy (Ansiedad 1)
        original_uc = UserChallenge.objects.create(
            user=self.user,
            terapia=self.terapia,
            challenge=self.challenge_ansiedad_1, # Reto Original
            available_date=today
        )
        original_uc_id = original_uc.id
        original_challenge_id = self.challenge_ansiedad_1.id

        # Asegurarse que hay otro reto disponible (Ansiedad 2 existe)
        self.assertTrue(Challenge.objects.filter(category=self.category_ansiedad, level=1).count() >= 2)

        url = reverse('therapy:replace_daily_challenge') # Asegúrate que este es el name= correcto
        response = self.client.post(url, {'terapia_id': self.terapia.id}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Verificar que el reto original fue eliminado
        self.assertFalse(UserChallenge.objects.filter(id=original_uc_id).exists())
        # Verificar que se creó un NUEVO reto para hoy
        self.assertTrue(UserChallenge.objects.filter(user=self.user, terapia=self.terapia, available_date=today).exists())
        new_uc = UserChallenge.objects.get(user=self.user, terapia=self.terapia, available_date=today)
        # Verificar que el nuevo reto NO es el original
        self.assertNotEqual(new_uc.challenge.id, original_challenge_id)
        # Verificar que el nuevo reto es el otro disponible (Ansiedad 2)
        self.assertEqual(new_uc.challenge.id, self.challenge_ansiedad_2.id)
        # Verificar la respuesta de la API
        self.assertEqual(response.data['id'], new_uc.id)
        self.assertEqual(response.data['challenge']['id'], self.challenge_ansiedad_2.id)

    def test_replace_daily_challenge_fail_when_no_challenge_today(self):
        """Verifica que falle el reemplazo si no hay reto pendiente hoy."""
        today = self.get_today_local_date()
        # Asegurarse que no hay reto hoy
        UserChallenge.objects.filter(user=self.user, terapia=self.terapia, available_date=today).delete()

        url = reverse('therapy:replace_daily_challenge')
        response = self.client.post(url, {'terapia_id': self.terapia.id}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('No hay un reto diario pendiente', response.data['error'])


    def test_replace_daily_challenge_fail_when_no_alternatives(self):
        """
        Verifica que falle el reemplazo si no hay otros retos disponibles
        en el mismo nivel y categoría activa.
        """
        today = self.get_today_local_date()
        # Eliminar el segundo reto de ansiedad para que solo quede uno
        self.challenge_ansiedad_2.delete()
        self.assertEqual(Challenge.objects.filter(category=self.category_ansiedad, level=1).count(), 1)

        # Crear el único reto disponible para hoy
        original_uc = UserChallenge.objects.create(
            user=self.user,
            terapia=self.terapia,
            challenge=self.challenge_ansiedad_1,
            available_date=today
        )
        original_uc_id = original_uc.id

        url = reverse('therapy:replace_daily_challenge')
        response = self.client.post(url, {'terapia_id': self.terapia.id}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('No se encontraron más retos alternativos', response.data['error'])
        # Importante: Verificar que el reto original SÍ fue eliminado
        self.assertFalse(UserChallenge.objects.filter(id=original_uc_id).exists())
        # Verificar que no se creó ningún reto nuevo
        self.assertFalse(UserChallenge.objects.filter(user=self.user, terapia=self.terapia, available_date=today).exists())
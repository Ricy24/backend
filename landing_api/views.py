# landing_api/views.py
from rest_framework import generics, status, serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Comment, NewsletterSubscription
from .serializers import CommentSerializer, CommentCreateSerializer, NewsletterSubscriptionSerializer

import requests # Para verificar reCAPTCHA
from django.conf import settings

class CommentListAPIView(generics.ListAPIView):
    """
    API para listar comentarios aprobados para un post_identifier específico.
    Se accede vía GET: /api/public/comments/?post_identifier=mi-slug-de-post
    """
    serializer_class = CommentSerializer
    permission_classes = [AllowAny] # Permite acceso sin autenticación

    def get_queryset(self):
        queryset = Comment.objects.filter(approved=True)
        post_identifier = self.request.query_params.get('post_identifier')
        if post_identifier:
            queryset = queryset.filter(post_identifier=post_identifier)
        return queryset.order_by('created_at') # Los más antiguos primero, o -created_at para los más nuevos

class CommentCreateAPIView(generics.CreateAPIView):
    queryset = Comment.objects.all()
    serializer_class = CommentCreateSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        # Verificar reCAPTCHA v3
        recaptcha_response_token = request.data.get('g-recaptcha-response')
        if not recaptcha_response_token:
            return Response({"detail": "Token de verificación reCAPTCHA requerido."}, status=status.HTTP_400_BAD_REQUEST)

        # Usa la CLAVE SECRETA de tus settings para la verificación del backend
        secret_key = settings.RECAPTCHA_PRIVATE_KEY 
        
        verification_data = {
            'secret': secret_key,
            'response': recaptcha_response_token
        }
        
        # Opcional: Enviar la IP del usuario para mejorar la evaluación de reCAPTCHA
        # x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        # remote_ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
        # if remote_ip:
        #     verification_data['remoteip'] = remote_ip
        
        r = requests.post('https://www.google.com/recaptcha/api/siteverify', data=verification_data)
        result = r.json()

        # Debug: Imprimir el resultado completo de la verificación de reCAPTCHA
        print("DEBUG reCAPTCHA verification result:", result)

        if not result.get('success'):
            error_codes = result.get('error-codes', [])
            print(f"reCAPTCHA v3 verification failed (success: false). Error codes: {error_codes}")
            # Puedes mapear error_codes a mensajes más amigables si quieres
            return Response({"detail": f"Falló la verificación reCAPTCHA. Código(s) de error: {', '.join(error_codes) if error_codes else 'Desconocido'}. Intenta de nuevo."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Verifica el score contra el umbral definido en settings.RECAPTCHA_REQUIRED_SCORE
        # Si RECAPTCHA_REQUIRED_SCORE no está en settings, getattr usará 0.5 por defecto.
        required_score = getattr(settings, 'RECAPTCHA_REQUIRED_SCORE', 0.5) 
        actual_score = result.get('score', 0) # El score devuelto por Google

        if actual_score < required_score:
            print(f"reCAPTCHA v3 score too low: {actual_score} (requerido: {required_score}). Action: {result.get('action')}")
            return Response({"detail": f"Falló la verificación reCAPTCHA (score bajo: {actual_score:.2f})."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Opcional: Verificar la 'action' si la definiste en el frontend
        # expected_action = 'submit_testimonial' # La acción que usaste en grecaptcha.execute
        # if result.get('action') != expected_action:
        #     print(f"reCAPTCHA v3 action mismatch: expected '{expected_action}', got '{result.get('action')}'")
        #     return Response({"detail": "Falló la verificación reCAPTCHA (acción incorrecta)."}, status=status.HTTP_400_BAD_REQUEST)

        # Si todo está bien con reCAPTCHA, proceder a crear el comentario
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except serializers.ValidationError as e:
            # Aquí el error es sobre los datos del comentario, no sobre reCAPTCHA
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(CommentSerializer(serializer.instance).data, status=status.HTTP_201_CREATED, headers=headers)
class NewsletterSubscriptionCreateAPIView(generics.CreateAPIView):
    """
    API para suscribirse al newsletter.
    Se accede vía POST: /api/public/subscribe/
    El payload debe incluir: email.
    """
    queryset = NewsletterSubscription.objects.all()
    serializer_class = NewsletterSubscriptionSerializer
    permission_classes = [AllowAny] # Permite acceso sin autenticación

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if NewsletterSubscription.objects.filter(email=request.data.get('email')).exists():
            return Response({"detail": "Este correo ya está suscrito."}, status=status.HTTP_400_BAD_REQUEST)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

# Para recomendaciones, necesitarías un modelo de "Post" o alguna forma de identificar tu contenido.
# Por ahora, vamos a dejar un placeholder, ya que depende de cómo organices tu contenido.
# class RecommendedPostsAPIView(generics.ListAPIView):
#     # queryset = Post.objects.filter(is_published=True, recommended=True).order_by('-publish_date')[:5]
#     # serializer_class = PostSerializer # Necesitarías un PostSerializer
#     permission_classes = [AllowAny]
#
#     def get(self, request, *args, **kwargs):
#         # Lógica para obtener recomendaciones
#         recommendations = [
#             {"id": 1, "title": "Post Recomendado 1", "slug": "post-recomendado-1"},
#             {"id": 2, "title": "Post Recomendado 2", "slug": "post-recomendado-2"},
#         ]
#         return Response(recommendations)
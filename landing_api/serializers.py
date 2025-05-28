# landing_api/serializers.py
from rest_framework import serializers
from .models import Comment, NewsletterSubscription

class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ['id', 'post_identifier', 'author_name', 'text', 'created_at']
        # No incluimos 'author_email' en la respuesta por privacidad,
        # ni 'approved' ya que solo mostraremos los aprobados.
        # 'post_identifier' también será necesario en el payload de creación.

class CommentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ['post_identifier', 'author_name', 'author_email', 'text']
        # 'author_email' es opcional para la creación
        extra_kwargs = {
            'author_email': {'required': False, 'allow_blank': True}
        }


class NewsletterSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsletterSubscription
        fields = ['id', 'email', 'subscribed_at']
        read_only_fields = ['id', 'subscribed_at'] # Solo queremos crear con el email
# community/serializers.py

from rest_framework import serializers
from django.contrib.auth import get_user_model # Para obtener el modelo de usuario
from .models import Post, Comment, Group
# Asegúrate de importar tu modelo de Usuario correctamente si no es el estándar
# from api.models import Usuario # Descomenta y ajusta si usas un modelo personalizado
Usuario = get_user_model()


# Serializer simple para mostrar info básica del autor
class UserSimpleSerializer(serializers.ModelSerializer):
    # Usa un SerializerMethodField para manejar nombres/emails
    username = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = ('id', 'username') # Puedes añadir más campos si los necesitas

    def get_username(self, obj):
         # Lógica para obtener un nombre de usuario presentable
         return obj.get_username() # El método estándar de User
         # O tu lógica personalizada si tienes un campo 'nombre':
         # return obj.nombre or obj.email.split('@')[0] or 'Anónimo'


# Serializer para los comentarios
class CommentSerializer(serializers.ModelSerializer):
    author = UserSimpleSerializer(read_only=True) # Usar el serializer de usuario simple

    class Meta:
        model = Comment
        fields = ('id', 'author', 'content', 'created_at')
        read_only_fields = ('id', 'author', 'created_at') # Author y fecha se establecen automáticamente


# Serializer para el grupo (simple, solo nombre e id)
class GroupSimpleSerializer(serializers.ModelSerializer):
     class Meta:
        model = Group
        fields = ('id', 'name')


# Serializer principal para el Post (para detalle y lista)
class PostSerializer(serializers.ModelSerializer):
    author = UserSimpleSerializer(read_only=True)
    # Usar el serializer de comentarios para el campo 'comments'
    comments = CommentSerializer(many=True, read_only=True)
    # Campos calculados que dependen del usuario que hace la request
    liked_by_user = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    # Mostrar info simple del grupo
    group = GroupSimpleSerializer(read_only=True)

    class Meta:
        model = Post
        fields = (
            'id',
            'author',
            'content',
            'created_at',
            'likes',
            'liked_by_user', # Campo calculado
            'comments_count',
            'comments',      # Lista de comentarios serializados
            'group',         # Info del grupo
            'is_saved'       # Campo calculado
        )
        # Campos que no se deben incluir al crear/actualizar directamente vía serializer
        read_only_fields = ('likes', 'liked_by_user', 'comments_count', 'is_saved', 'created_at', 'author')

    # Método para determinar si el usuario actual dio like
    def get_liked_by_user(self, obj):
        # 'request' debe estar en el contexto del serializer
        request = self.context.get('request', None)
        if request and request.user.is_authenticated:
            # obj es la instancia del Post
            return obj.liked_users.filter(id=request.user.id).exists()
        return False # No autenticado o sin request

    # Método para determinar si el usuario actual guardó el post
    def get_is_saved(self, obj):
        request = self.context.get('request', None)
        if request and request.user.is_authenticated:
             # Asume que el related_name es 'saved_by' como en tu modelo
             # Si cambiaste el related_name a 'saved_community_posts', usa ese:
             # return obj.saved_community_posts.filter(id=request.user.id).exists()
             return obj.saved_by.filter(id=request.user.id).exists()
        return False
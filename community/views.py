# community/views.py
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import Post, Group, Blog, FeaturedContent, Comment # Import Comment
from api.models import Usuario
from notifications.models import Notification
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone
from django.db.models import F, Q
from django.conf import settings

logger = logging.getLogger(__name__)

# --- PostView ---
# (GET y POST sin cambios)
# community/views.py
class PostView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, post_id=None):
        try:
            user = request.user
            if post_id is not None:
                post = get_object_or_404(Post, id=post_id)
                if post.group and not post.group.members.filter(id=user.id).exists():
                    return Response({'error': 'No tienes permiso para ver este post'}, status=status.HTTP_403_FORBIDDEN)

                data = {
                    'id': post.id,
                    'author': {
                        'id': post.author.id,
                        'username': post.author.nombre or post.author.email.split('@')[0] or 'Anónimo',
                    } if post.author else None,
                    'content': post.content,
                    'created_at': post.created_at.isoformat(),
                    'likes': post.likes,
                    'liked_by_user': post.liked_users.filter(id=user.id).exists(),
                    'comments_count': post.comments_count,
                    'comments': [
                        {
                            'id': comment.id,
                            'author': {
                                'id': comment.author.id,
                                'username': comment.author.nombre or comment.author.email.split('@')[0] or 'Anónimo',
                            } if comment.author else None,
                            'content': comment.content,
                            'created_at': comment.created_at.isoformat(),
                        } for comment in post.comments.all().order_by('created_at')
                    ],
                    'group': {'id': post.group.id, 'name': post.group.name} if post.group else None,
                    'is_saved': post.saved_by.filter(id=user.id).exists(),
                    'shared_from': post.shared_from.id if post.shared_from else None,
                }
                return Response(data, status=status.HTTP_200_OK)
            else:
                posts = Post.objects.filter(
                    Q(group__isnull=True) | Q(group__members=user)
                ).select_related('author', 'group').prefetch_related(
                    'liked_users', 'saved_by', 'comments__author'
                ).order_by('-created_at')

                data = [
                    {
                        'id': post.id,
                        'author': {
                            'id': post.author.id,
                            'username': post.author.nombre or post.author.email.split('@')[0] or 'Anónimo',
                        } if post.author else None,
                        'content': post.content,
                        'created_at': post.created_at.isoformat(),
                        'likes': post.likes,
                        'liked_by_user': user in post.liked_users.all(),
                        'comments_count': post.comments_count,
                        'comments': [
                            {
                                'id': comment.id,
                                'author': {
                                    'id': comment.author.id,
                                    'username': comment.author.nombre or comment.author.email.split('@')[0] or 'Anónimo',
                                } if comment.author else None,
                                'content': comment.content,
                                'created_at': comment.created_at.isoformat(),
                            } for comment in post.comments.all().order_by('created_at')[:3]
                        ],
                        'group': {'id': post.group.id, 'name': post.group.name} if post.group else None,
                        'is_saved': user in post.saved_by.all(),
                        'shared_from': post.shared_from.id if post.shared_from else None,
                    }
                    for post in posts
                ]
                return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en PostView GET: {str(e)}")
            return Response({'error': 'Ocurrió un error al obtener los posts.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        try:
            content = request.data.get('content')
            group_id = request.data.get('group_id')
            shared_from_id = request.data.get('shared_from')
            if not content:
                return Response({'error': 'El contenido es obligatorio'}, status=status.HTTP_400_BAD_REQUEST)

            group = None
            if group_id:
                group = get_object_or_404(Group, id=group_id)
                if not group.members.filter(id=request.user.id).exists():
                    return Response({'error': 'Debes ser miembro del grupo para publicar en él'}, status=status.HTTP_403_FORBIDDEN)

            shared_from = None
            if shared_from_id:
                shared_from = get_object_or_404(Post, id=shared_from_id)

            post = Post.objects.create(
                author=request.user,
                content=content,
                group=group,
                shared_from=shared_from,
            )

            data = {
                'id': post.id,
                'author': {
                    'id': post.author.id,
                    'username': post.author.nombre or post.author.email.split('@')[0] or 'Anónimo',
                },
                'content': post.content,
                'created_at': post.created_at.isoformat(),
                'likes': 0,
                'liked_by_user': False,
                'comments_count': 0,
                'comments': [],
                'group': {'id': group.id, 'name': group.name} if group else None,
                'is_saved': False,
                'shared_from': post.shared_from.id if post.shared_from else None,
            }
            return Response(data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error en PostView POST: {str(e)}")
            return Response({'error': 'Ocurrió un error al crear el post.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, post_id):
        try:
            post = get_object_or_404(Post, id=post_id)
            user = request.user

            # Verificar si el usuario actual es el autor del post
            if post.author != user:
                logger.warning(f"Usuario {user.id} intentó eliminar post {post.id} de autor {post.author.id}")
                return Response({'error': 'No tienes permiso para eliminar este post'}, status=status.HTTP_403_FORBIDDEN)

            # Eliminar el post
            post_content_preview = post.content[:50] + ("..." if len(post.content) > 50 else "")
            post.delete()
            logger.info(f"Usuario {user.id} eliminó post {post_id} (contenido: '{post_content_preview}')")

            # Devolver respuesta exitosa sin contenido
            return Response(status=status.HTTP_204_NO_CONTENT)

        except Post.DoesNotExist:
             # El get_object_or_404 ya maneja esto, pero por si acaso
             return Response({'error': 'Post no encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error en PostView DELETE (post_id={post_id}): {str(e)}")
            return Response({'error': 'Ocurrió un error al eliminar el post.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- Resto de las vistas (LikePostView, SharePostView, etc.) sin cambios ---
# ... (mantén el resto de tus vistas como estaban) ...
class LikePostView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, post_id):
        try:
            post = get_object_or_404(Post, id=post_id)
            user = request.user
            channel_layer = get_channel_layer()
            if post.liked_users.filter(id=user.id).exists():
                post.liked_users.remove(user)
                post.likes = F('likes') - 1
            else:
                post.liked_users.add(user)
                post.likes = F('likes') + 1
                if post.author != user:
                    Notification.objects.create( recipient=post.author, notification_type='like', message=f"A {user.username or user.email.split('@')[0]} le gusta tu post", related_object_id=str(post.id) )
                    async_to_sync(channel_layer.group_send)( f"user_{post.author.id}", { 'type': 'send_notification', 'notification_type': 'like', 'message': f"A {user.username or user.email.split('@')[0]} le gusta tu post", 'created_at': timezone.now().isoformat(), 'related_object_id': str(post.id), } )
            post.save(update_fields=['likes']) # Optimiza guardando solo el campo necesario
            post.refresh_from_db(fields=['likes']) # Recarga solo el campo
            return Response({ 'id': post.id, 'likes': post.likes, 'liked_by_user': post.liked_users.filter(id=user.id).exists(), }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en LikePostView POST: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SharePostView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, post_id):
        try:
            post = get_object_or_404(Post, id=post_id)
            # Esta vista actualmente solo devuelve la URL, la lógica de crear
            # el post compartido está en el frontend. Mantenemos esto así por ahora.
            share_url = f"{settings.FRONTEND_URL}/community/post/{post.id}" # Asegúrate que FRONTEND_URL esté en settings
            return Response({'share_url': share_url}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en SharePostView POST: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CommentPostView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, post_id):
        try:
            post = get_object_or_404(Post, id=post_id)
            content = request.data.get('content')
            if not content: return Response({'error': 'Comment content is required'}, status=status.HTTP_400_BAD_REQUEST)
            comment = Comment.objects.create( post=post, author=request.user, content=content, )
            post.comments_count = F('comments_count') + 1
            post.save(update_fields=['comments_count'])
            post.refresh_from_db(fields=['comments_count'])
            channel_layer = get_channel_layer()
            if post.author != request.user:
                Notification.objects.create( recipient=post.author, notification_type='comment', message=f"{request.user.username or request.user.email.split('@')[0]} comentó tu post", related_object_id=str(post.id) )
                async_to_sync(channel_layer.group_send)( f"user_{post.author.id}", { 'type': 'send_notification', 'notification_type': 'comment', 'message': f"{request.user.username or request.user.email.split('@')[0]} comentó tu post", 'created_at': timezone.now().isoformat(), 'related_object_id': str(post.id), } )
            return Response({ 'id': comment.id, 'author': { 'id': comment.author.id, 'username': comment.author.username or comment.author.email.split('@')[0] or 'Anónimo', }, 'content': comment.content, 'created_at': comment.created_at.isoformat(), 'post_comments_count': post.comments_count, }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error en CommentPostView POST: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class GroupView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            groups = Group.objects.prefetch_related('members')  # Optimizar
            user = request.user
            # Contar en Python es más simple aquí
            data = [
                {
                    'id': group.id,
                    'name': group.name,
                    'icon': group.icon,
                    'members_count': group.members.count(),
                    'is_member': user in group.members.all()
                } for group in groups
            ]
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en GroupView GET: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def post(self, request):
        try:
            name = request.data.get('name')
            icon = request.data.get('icon', 'Users')
            if not name:
                return Response({'error': 'Group name is required'}, status=status.HTTP_400_BAD_REQUEST)
            group = Group.objects.create(name=name, icon=icon)
            group.members.add(request.user)
            return Response(
                {
                    'id': group.id,
                    'name': group.name,
                    'icon': group.icon,
                    'members_count': 1,
                    'is_member': True
                },
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            logger.error(f"Error en GroupView POST: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class JoinGroupView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, group_id):
        try:
            group = get_object_or_404(Group.objects.prefetch_related('members'), id=group_id)
            user = request.user
            if user in group.members.all():
                return Response({'message': f'Ya eres miembro de {group.name}', 'members_count': group.members.count()}, status=status.HTTP_200_OK)
            group.members.add(user)
            return Response({ 'message': f'Unido al grupo {group.name}', 'members_count': group.members.count(), }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en JoinGroupView POST: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ActiveMembersView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        try:
            # Una lógica más simple: usuarios que han posteado o comentado recientemente
            recent_post_authors = Post.objects.filter(created_at__gte=timezone.now() - timezone.timedelta(days=7)).values_list('author_id', flat=True).distinct()
            recent_comment_authors = Comment.objects.filter(created_at__gte=timezone.now() - timezone.timedelta(days=7)).values_list('author_id', flat=True).distinct()
            active_user_ids = set(recent_post_authors) | set(recent_comment_authors)
            active_users = Usuario.objects.filter(id__in=active_user_ids)
            data = [ { 'id': user.id, 'username': user.username or user.email.split('@')[0] or 'Anónimo', } for user in active_users[:20] ] # Limitar por si son muchos
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en ActiveMembersView GET: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class BlogView(APIView):
    permission_classes = [IsAuthenticated] # O IsAuthenticatedOrReadOnly si quieres que sean públicos
    def get(self, request):
        try:
            blogs = Blog.objects.all().order_by('-date')
            data = [ { 'id': blog.id, 'title': blog.title, 'excerpt': blog.excerpt, 'image': blog.image, 'date': blog.date.isoformat(), 'read_time': blog.read_time, } for blog in blogs ]
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en BlogView GET: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class FeaturedContentView(APIView):
    permission_classes = [IsAuthenticated] # O IsAuthenticatedOrReadOnly
    def get(self, request):
        try:
            content = FeaturedContent.objects.all()
            data = [ { 'id': item.id, 'title': item.title, 'type': item.type, 'icon': item.icon, 'downloads': item.downloads, } for item in content ]
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en FeaturedContentView GET: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SavePostView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, post_id):
        try:
            post = get_object_or_404(Post, id=post_id)
            user = request.user
            if post.saved_by.filter(id=user.id).exists():
                post.saved_by.remove(user)
                is_saved = False
            else:
                post.saved_by.add(user)
                is_saved = True
            # No necesitamos .save() aquí porque es una relación ManyToMany
            return Response({'id': post.id, 'is_saved': is_saved}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en SavePostView POST: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
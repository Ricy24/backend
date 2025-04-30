# community/models.py
from django.db import models
from api.models import Usuario
from django.utils import timezone

class Post(models.Model):
    author = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='community_posts')
    content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    likes = models.PositiveIntegerField(default=0)
    liked_users = models.ManyToManyField(Usuario, related_name='liked_posts', blank=True)
    comments_count = models.PositiveIntegerField(default=0)
    group = models.ForeignKey('Group', on_delete=models.CASCADE, null=True, blank=True, related_name='posts')
    saved_by = models.ManyToManyField(Usuario, related_name='saved_community_posts', blank=True)
    shared_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='shared_posts')  # Nuevo campo

    class Meta:
        db_table = 'comunidad_post'

    def __str__(self):
        return f"Post by {self.author.username or self.author.email} at {self.created_at}"

# Resto de los modelos sin cambios
class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='comments')
    content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'comunidad_comment'

    def __str__(self):
        return f"Comment by {self.author.username or self.author.email} on {self.post}"

class Group(models.Model):
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=50, default='Users')
    members = models.ManyToManyField(Usuario, related_name='community_groups')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'comunidad_group'

    def members_count(self):
        return self.members.count()

    def __str__(self):
        return self.name

class Blog(models.Model):
    title = models.CharField(max_length=200)
    excerpt = models.TextField()
    image = models.URLField(blank=True, null=True)
    date = models.DateTimeField(default=timezone.now)
    read_time = models.CharField(max_length=20, default='5 min')

    class Meta:
        db_table = 'comunidad_blog'

    def __str__(self):
        return self.title

class FeaturedContent(models.Model):
    title = models.CharField(max_length=200)
    type = models.CharField(max_length=50)
    icon = models.CharField(max_length=50, default='FileText')
    downloads = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'comunidad_featuredcontent'

    def __str__(self):
        return self.title
# community/admin.py
from django.contrib import admin
from django import forms
from .models import Post, Comment, Group, Blog, FeaturedContent
from api.models import Usuario

class CommentInline(admin.TabularInline):
    model = Comment
    extra = 1
    readonly_fields = ('created_at',)
    fields = ('author', 'content', 'created_at')

class PostAdminForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limitar usuarios a los disponibles
        self.fields['author'].queryset = Usuario.objects.all()
        self.fields['liked_users'].queryset = Usuario.objects.all()
        self.fields['saved_by'].queryset = Usuario.objects.all()

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    form = PostAdminForm
    inlines = [CommentInline]
    list_display = (
        'id',
        'author_email',
        'content_preview',
        'group_name',
        'created_at',
        'likes',
        'comments_count',
        'is_shared',
    )
    list_filter = (
        'created_at',
        'group',
        'likes',
    )
    search_fields = (
        'content',
        'author__email',
        'author__nombre',
        'group__name',
    )
    readonly_fields = (
        'created_at',
        'likes',
        'comments_count',
    )
    fieldsets = (
        ('Información Principal', {
            'fields': ('author', 'content', 'group', 'shared_from')
        }),
        ('Interacciones', {
            'fields': ('liked_users', 'saved_by', 'likes', 'comments_count')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )
    filter_horizontal = ('liked_users', 'saved_by')

    def author_email(self, obj):
        return obj.author.email
    author_email.short_description = 'Autor'

    def content_preview(self, obj):
        return obj.content[:50] + ('...' if len(obj.content) > 50 else '')
    content_preview.short_description = 'Contenido'

    def group_name(self, obj):
        return obj.group.name if obj.group else '-'
    group_name.short_description = 'Grupo'

    def is_shared(self, obj):
        return bool(obj.shared_from)
    is_shared.boolean = True
    is_shared.short_description = 'Compartido'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('author', 'group', 'shared_from').prefetch_related('liked_users', 'saved_by', 'comments')

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'post_preview',
        'author_email',
        'content_preview',
        'created_at',
    )
    list_filter = (
        'created_at',
        'post',
    )
    search_fields = (
        'content',
        'author__email',
        'author__nombre',
        'post__content',
    )
    readonly_fields = ('created_at',)
    fieldsets = (
        ('Información', {
            'fields': ('post', 'author', 'content')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )

    def author_email(self, obj):
        return obj.author.email
    author_email.short_description = 'Autor'

    def post_preview(self, obj):
        return obj.post.content[:30] + ('...' if len(obj.post.content) > 30 else '')
    post_preview.short_description = 'Post'

    def content_preview(self, obj):
        return obj.content[:50] + ('...' if len(obj.content) > 50 else '')
    content_preview.short_description = 'Contenido'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('post', 'author')

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'icon',
        'members_count',
        'created_at',
    )
    list_filter = (
        'created_at',
        'icon',
    )
    search_fields = (
        'name',
        'members__email',
        'members__nombre',
    )
    filter_horizontal = ('members',)
    readonly_fields = ('created_at',)
    fieldsets = (
        ('Información', {
            'fields': ('name', 'icon')
        }),
        ('Miembros', {
            'fields': ('members',)
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )

    def members_count(self, obj):
        return obj.members.count()
    members_count.short_description = 'Nº Miembros'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('members')

@admin.register(Blog)
class BlogAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'read_time',
        'date',
    )
    list_filter = (
        'date',
    )
    search_fields = (
        'title',
        'excerpt',
    )
    readonly_fields = ('date',)
    fieldsets = (
        ('Contenido', {
            'fields': ('title', 'excerpt', 'image', 'read_time')
        }),
        ('Metadata', {
            'fields': ('date',),
            'classes': ('collapse',),
        }),
    )

@admin.register(FeaturedContent)
class FeaturedContentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'type',
        'icon',
        'downloads',
    )
    list_filter = (
        'type',
        'icon',
    )
    search_fields = (
        'title',
    )
    fieldsets = (
        ('Contenido', {
            'fields': ('title', 'type', 'icon', 'downloads')
        }),
    )
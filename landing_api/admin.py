# landing_api/admin.py
from django.contrib import admin
from .models import Comment, NewsletterSubscription

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('post_identifier', 'author_name', 'text_preview', 'created_at', 'approved')
    list_filter = ('approved', 'created_at', 'post_identifier')
    search_fields = ('author_name', 'author_email', 'text', 'post_identifier')
    actions = ['approve_comments', 'disapprove_comments']

    def text_preview(self, obj):
        return obj.text[:50] + "..." if len(obj.text) > 50 else obj.text
    text_preview.short_description = 'Text'

    def approve_comments(self, request, queryset):
        queryset.update(approved=True)
    approve_comments.short_description = "Approve selected comments"

    def disapprove_comments(self, request, queryset):
        queryset.update(approved=False)
    disapprove_comments.short_description = "Disapprove selected comments"


@admin.register(NewsletterSubscription)
class NewsletterSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('email', 'subscribed_at', 'is_active')
    list_filter = ('is_active', 'subscribed_at')
    search_fields = ('email',)
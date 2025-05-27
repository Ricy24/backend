# landing_api/urls.py
from django.urls import path
from .views import (
    CommentListAPIView,
    CommentCreateAPIView,
    NewsletterSubscriptionCreateAPIView,
    # RecommendedPostsAPIView
)

app_name = 'landing_api'

urlpatterns = [
    path('comments/', CommentListAPIView.as_view(), name='comment-list'),
    path('comments/create/', CommentCreateAPIView.as_view(), name='comment-create'),
    path('subscribe/', NewsletterSubscriptionCreateAPIView.as_view(), name='newsletter-subscribe'),
    # path('recommendations/', RecommendedPostsAPIView.as_view(), name='recommendations-list'),
]
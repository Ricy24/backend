# community/urls.py
from django.urls import path
from .views import (
    PostView, GroupView, JoinGroupView, ActiveMembersView, BlogView,
    FeaturedContentView, LikePostView, SharePostView, CommentPostView, SavePostView
)

urlpatterns = [
    path('posts/', PostView.as_view(), name='posts'),
    path('posts/<int:post_id>/', PostView.as_view(), name='post_detail_or_delete'),
    path('posts/<int:post_id>/like/', LikePostView.as_view(), name='like_post'),
    path('posts/<int:post_id>/share/', SharePostView.as_view(), name='share_post'),
    path('posts/<int:post_id>/comment/', CommentPostView.as_view(), name='comment_post'),
    path('posts/<int:post_id>/save/', SavePostView.as_view(), name='save_post'),
    path('groups/', GroupView.as_view(), name='groups'),
    path('groups/<int:group_id>/join/', JoinGroupView.as_view(), name='join_group'),
    path('active-members/', ActiveMembersView.as_view(), name='active_members'),
    path('blogs/', BlogView.as_view(), name='blogs'),
    path('featured-content/', FeaturedContentView.as_view(), name='featured_content'),
]
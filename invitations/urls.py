from django.urls import path
from .views import InviteFriendView, AcceptInvitationView, UserRewardsView, InvitedUsersView

urlpatterns = [
    path('invite/', InviteFriendView.as_view(), name='invite_friend'),
    path('accept-invitation/', AcceptInvitationView.as_view(), name='accept_invitation'),
    path('rewards/', UserRewardsView.as_view(), name='user_rewards'),
    path('invited-users/', InvitedUsersView.as_view(), name='invited_users'),
]
# serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Invitation, Reward

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ['id', 'invite_code', 'created_at', 'is_accepted', 'accepted_at']

class RewardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reward
        fields = ['id', 'description', 'points', 'awarded_at', 'is_redeemed']
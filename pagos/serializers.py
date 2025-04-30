from rest_framework import serializers
from .models import PaymentMethod, Payment

class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ['id', 'provider', 'card_last_four', 'card_brand', 'created_at']

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['id', 'transaction_id', 'amount', 'currency', 'provider', 'status', 'method', 'card_last_four', 'created_at', 'description']
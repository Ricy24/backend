# pagos/urls.py
from django.urls import path
from .views import (
    InitiateCheckoutView,
    WebhookPayUView,
    WebhookMercadoPagoView,
    PaymentHistoryView,
    PaymentMethodListView,
    RefundView,
    RequestRefundSupportView,
)

app_name = 'pagos'

urlpatterns = [
    path('payment-methods/', PaymentMethodListView.as_view(), name='payment-methods'),
    path('payment-history/', PaymentHistoryView.as_view(), name='payment-history'),
    path('initiate-checkout/', InitiateCheckoutView.as_view(), name='initiate-checkout'),
    path('webhook/payu/', WebhookPayUView.as_view(), name='webhook-payu'),
    path('webhook/mercadopago/', WebhookMercadoPagoView.as_view(), name='webhook-mercadopago'),
    path('refund/', RefundView.as_view(), name='refund'),
    path('request-refund-support/', RequestRefundSupportView.as_view(), name='request-refund-support'),
]
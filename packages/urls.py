# packages/urls.py
from django.urls import path
from .views import (
    PricingOptionsView,  # Nueva vista para mostrar opciones
    CalculatePriceView,  # Nueva vista para calcular precio
    InitiatePurchaseView,
    UserPurchasesView,
)

urlpatterns = [
    # path('packages/', PackageListView.as_view(), name='package-list'), # Puedes eliminar o comentar esta
    path('pricing-options/', PricingOptionsView.as_view(), name='pricing-options'),
    path('calculate-price/', CalculatePriceView.as_view(), name='calculate-price'),
    path('initiate-purchase/', InitiatePurchaseView.as_view(), name='initiate-purchase'),
    path('my-purchases/', UserPurchasesView.as_view(), name='user-purchases'),
]
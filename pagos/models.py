# pagos/models.py
from django.db import models
from django.contrib.auth import get_user_model
# from django.conf import settings # No se necesita aquí

User = get_user_model()

class PaymentMethod(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_methods') # related_name ok
    provider = models.CharField(max_length=50, choices=[('payu', 'PayU')])
    card_last_four = models.CharField(max_length=4)
    card_brand = models.CharField(max_length=50)
    # Considera unique=True si este ID debe ser único por usuario/proveedor
    payment_method_id = models.CharField(max_length=255, unique=True, null=True, blank=True) # ID/Token de PayU para tarjeta guardada
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
         # Usa email como fallback si existe
         user_display = getattr(self.user, 'email', str(self.user.pk))
         return f"{self.card_brand} ****{self.card_last_four} ({user_display})"


class Payment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='COP')
    provider = models.CharField(max_length=50, choices=[('payu', 'PayU'), ('mercadopago', 'Mercado Pago')])
    transaction_id = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded')  # Añadimos estado "refunded"
    ])
    method = models.CharField(max_length=50, blank=True, null=True)  # Nuevo campo para método de pago
    card_last_four = models.CharField(max_length=4, blank=True, null=True)  # Para tarjetas
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        user_display = getattr(self.user, 'email', str(self.user.pk))
        return f"Pago {self.transaction_id} - {self.amount} {self.currency} por {user_display} ({self.status})"
# --- YA NO SE DEFINEN Package NI Purchase AQUÍ ---
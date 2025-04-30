# plant/urls.py
from django.urls import path
from .views import PlantDetailView,PublicPlantView, CarePlantView, CustomizePlantView

print("Cargando plant/urls.py")  # Debugging
urlpatterns = [
    path('terapia/<int:terapia_id>/plant/', PlantDetailView.as_view(), name='plant_detail'),
    path('terapia/<int:terapia_id>/plant/public/', PublicPlantView.as_view(), name='plant_public'),
    path('terapia/<int:terapia_id>/plant/care/', CarePlantView.as_view(), name='care_plant'),
    path('terapia/<int:terapia_id>/plant/customize/', CustomizePlantView.as_view(), name='customize_plant'),
]
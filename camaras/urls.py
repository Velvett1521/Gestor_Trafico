from django.urls import path
from . import views

urlpatterns = [
    path('', views.monitor, name='monitor'),
    path('detectar/', views.detectar, name='detectar'),
]

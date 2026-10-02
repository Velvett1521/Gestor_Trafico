from django.urls import path
from . import views

urlpatterns = [
    path('', views.monitor, name='monitor'),
    path('detectar/', views.detectar, name='detectar'),
    path('camaras/<int:camara_id>/reiniciar/', views.reiniciar, name='reiniciar_conteo'),
    path('camaras/<int:camara_id>/analisis/', views.analisis, name='analisis_camara'),
    path('intersecciones/<int:interseccion_id>/gestion/', views.gestion_interseccion, name='gestion_interseccion'),
    path('alertas/', views.alertas, name='alertas'),
]

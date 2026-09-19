from django.contrib import admin
from .models import Interseccion, Camara, ConteoVehiculo


@admin.register(Interseccion)
class InterseccionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'latitud', 'longitud', 'creada')


@admin.register(Camara)
class CamaraAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'interseccion', 'tipo', 'activa')
    list_filter = ('tipo', 'activa')


@admin.register(ConteoVehiculo)
class ConteoVehiculoAdmin(admin.ModelAdmin):
    list_display = ('camara', 'marca_tiempo', 'clase', 'cantidad')
    list_filter = ('camara', 'clase')
    date_hierarchy = 'marca_tiempo'

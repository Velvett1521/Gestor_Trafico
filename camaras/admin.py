from django.contrib import admin
from .models import Interseccion, Camara, ConteoVehiculo, DecisionSemaforo


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


@admin.register(DecisionSemaforo)
class DecisionSemaforoAdmin(admin.ModelAdmin):
    list_display = ('interseccion', 'marca_tiempo', 'camara_favorecida', 'regla_aplicada')
    list_filter = ('interseccion', 'regla_aplicada')
    date_hierarchy = 'marca_tiempo'
    readonly_fields = ('marca_tiempo',)

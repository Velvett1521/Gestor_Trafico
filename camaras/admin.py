from django.contrib import admin
from .models import Interseccion, Camara


@admin.register(Interseccion)
class InterseccionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'latitud', 'longitud', 'creada')


@admin.register(Camara)
class CamaraAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'interseccion', 'tipo', 'activa')
    list_filter = ('tipo', 'activa')

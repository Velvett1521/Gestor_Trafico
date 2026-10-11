from django.apps import AppConfig


class CamarasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'camaras'

    def ready(self):
        from . import deteccion
        deteccion.arrancar_volcador()
from django.db import models


class Interseccion(models.Model):
    nombre = models.CharField(max_length=120)
    latitud = models.FloatField(null=True, blank=True)
    longitud = models.FloatField(null=True, blank=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'intersección'
        verbose_name_plural = 'intersecciones'

    def __str__(self):
        return self.nombre


class Camara(models.Model):
    TIPO_CHOICES = [
        ('local', 'Cámara del dispositivo'),
        ('rtsp', 'Cámara IP (RTSP)'),
    ]
    interseccion = models.ForeignKey(
        Interseccion, on_delete=models.CASCADE, related_name='camaras'
    )
    nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='local')
    url_rtsp = models.CharField(
        max_length=300, blank=True,
        help_text='Solo para cámaras IP. Se usará cuando se integre la IA.'
    )
    activa = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.nombre} ({self.interseccion})'

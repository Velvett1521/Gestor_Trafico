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


class ConteoVehiculo(models.Model):
    """
    Un registro por (cámara, franja de tiempo, clase de vehículo).
    La franja se trunca a nivel minuto (ver `deteccion.registrar_conteo`)
    para poder agregar por hora/día y comparar tráfico actual vs. histórico
    sin escanear un registro por vehículo individual.
    """
    camara = models.ForeignKey(
        Camara, on_delete=models.CASCADE, related_name='conteos'
    )
    marca_tiempo = models.DateTimeField(db_index=True)
    clase = models.CharField(max_length=20)
    cantidad = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'conteo de vehículos'
        verbose_name_plural = 'conteos de vehículos'
        constraints = [
            models.UniqueConstraint(
                fields=['camara', 'marca_tiempo', 'clase'],
                name='conteo_unico_por_minuto_y_clase',
            )
        ]
        indexes = [
            models.Index(fields=['camara', 'marca_tiempo']),
        ]

    def __str__(self):
        return f'{self.camara} · {self.marca_tiempo:%Y-%m-%d %H:%M} · {self.clase}: {self.cantidad}'

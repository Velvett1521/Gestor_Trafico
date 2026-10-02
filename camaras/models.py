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


class DecisionSemaforo(models.Model):
    """
    Bitácora de cada decisión que tomó el motor de reglas de gestión de
    tráfico para una intersección: qué cámara/carril recibió más verde,
    por qué (regla aplicada) y con qué datos de tráfico se calculó.
    Sirve para auditar la simulación, no solo para mostrar el estado
    actual del semáforo virtual.
    """
    interseccion = models.ForeignKey(
        Interseccion, on_delete=models.CASCADE, related_name='decisiones_semaforo'
    )
    marca_tiempo = models.DateTimeField(auto_now_add=True, db_index=True)
    camara_favorecida = models.ForeignKey(
        Camara, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='decisiones_favorecida',
    )
    segundos_verde_favorecida = models.PositiveIntegerField()
    segundos_verde_resto = models.PositiveIntegerField()
    regla_aplicada = models.CharField(max_length=60)
    justificacion = models.TextField()

    class Meta:
        verbose_name = 'decisión de semáforo'
        verbose_name_plural = 'decisiones de semáforo'
        ordering = ['-marca_tiempo']

    def __str__(self):
        return f'{self.interseccion} · {self.marca_tiempo:%H:%M:%S} · {self.regla_aplicada}'

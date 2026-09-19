"""
Análisis de tránsito a partir de los registros agregados en
ConteoVehiculo: comparación contra el histórico del mismo horario/día,
detección de congestión y tendencia por hora del día.
"""
from datetime import timedelta

from django.db.models import Sum
from django.db.models.functions import TruncHour
from django.utils import timezone

from .models import ConteoVehiculo

# Vehículos/minuto a partir del cual se considera "congestión". Es un
# valor de arranque razonable para una vía urbana de un solo carril;
# ajústalo según la intersección real una vez que tengas datos.
UMBRAL_CONGESTION_POR_MINUTO = 8

# Cuántas semanas hacia atrás se consideran "histórico" al comparar el
# tráfico actual contra el promedio de esa misma hora y día de la semana.
SEMANAS_HISTORICO = 8


def _promedio_historico(camara_id: int, momento) -> float:
    """
    Promedio de vehículos/minuto registrados históricamente para esta
    cámara, en la MISMA hora del día y el MISMO día de la semana que
    `momento` (para comparar un lunes 8am contra otros lunes 8am, no
    contra el tráfico general).
    """
    momento_local = timezone.localtime(momento)
    desde = momento - timedelta(weeks=SEMANAS_HISTORICO)
    registros = ConteoVehiculo.objects.filter(
        camara_id=camara_id,
        marca_tiempo__gte=desde,
        marca_tiempo__lt=momento.replace(second=0, microsecond=0),
    )
    # Se filtra hora/día en Python (sobre la hora ya convertida a local)
    # en vez de con __hour/__week_day de Django, porque esos lookups
    # operan sobre el valor tal como está en la base de datos (UTC en
    # SQLite con USE_TZ=True) y no aplican automáticamente TIME_ZONE.
    registros = [
        r for r in registros
        if timezone.localtime(r.marca_tiempo).hour == momento_local.hour
        and timezone.localtime(r.marca_tiempo).weekday() == momento_local.weekday()
    ]
    if not registros:
        return 0.0
    minutos_distintos = len({r.marca_tiempo for r in registros})
    total = sum(r.cantidad for r in registros)
    return total / minutos_distintos


def analizar_camara(camara_id: int) -> dict:
    """
    Devuelve un panorama del tránsito de la cámara:

        {
          "vehiculos_ultimos_5min": 23,
          "ritmo_por_minuto": 4.6,
          "promedio_historico_mismo_horario": 3.1,
          "variacion_pct": 48.4,           # % sobre el histórico (+ = más tráfico de lo usual)
          "congestion": False,
          "hora_pico_hoy": {"hora": 8, "vehiculos": 142},
          "tendencia_por_hora": [{"hora": 0, "vehiculos": 3}, ..., {"hora": 23, "vehiculos": 12}],
          "por_clase_ultimos_5min": {"auto": 18, "moto": 3, "camion": 2},
        }

    Si no hay suficientes datos todavía, los campos comparativos regresan
    None/0 en vez de fallar, para que la UI pueda mostrar "aún sin
    histórico" en lugar de un error.
    """
    ahora = timezone.now()
    desde_5min = ahora - timedelta(minutes=5)

    ventana = ConteoVehiculo.objects.filter(camara_id=camara_id, marca_tiempo__gte=desde_5min)
    vehiculos_5min = ventana.aggregate(suma=Sum('cantidad'))['suma'] or 0
    ritmo_por_minuto = round(vehiculos_5min / 5, 2)

    por_clase = {}
    for fila in ventana.values('clase').annotate(total=Sum('cantidad')):
        por_clase[fila['clase']] = fila['total']

    promedio_historico = round(_promedio_historico(camara_id, ahora), 2)
    if promedio_historico > 0:
        variacion_pct = round((ritmo_por_minuto - promedio_historico) / promedio_historico * 100, 1)
    else:
        variacion_pct = None  # sin histórico suficiente todavía

    ahora_local = timezone.localtime(ahora)
    hoy = ahora_local.replace(hour=0, minute=0, second=0, microsecond=0)
    conteos_hoy = ConteoVehiculo.objects.filter(camara_id=camara_id, marca_tiempo__gte=hoy)

    # TruncHour trunca respetando settings.TIME_ZONE (a diferencia de un
    # strftime crudo sobre el valor almacenado, que en SQLite queda en UTC).
    tendencia = (
        conteos_hoy
        .annotate(bloque_hora=TruncHour('marca_tiempo'))
        .values('bloque_hora')
        .annotate(vehiculos=Sum('cantidad'))
        .order_by('bloque_hora')
    )
    tendencia_por_hora = [
        {"hora": timezone.localtime(t['bloque_hora']).hour, "vehiculos": t['vehiculos']}
        for t in tendencia
    ]
    hora_pico_hoy = max(tendencia_por_hora, key=lambda t: t['vehiculos'], default=None)
    if hora_pico_hoy:
        hora_pico_hoy = {"hora": hora_pico_hoy["hora"], "vehiculos": hora_pico_hoy["vehiculos"]}

    return {
        "vehiculos_ultimos_5min": vehiculos_5min,
        "ritmo_por_minuto": ritmo_por_minuto,
        "promedio_historico_mismo_horario": promedio_historico or None,
        "variacion_pct": variacion_pct,
        "congestion": ritmo_por_minuto >= UMBRAL_CONGESTION_POR_MINUTO,
        "hora_pico_hoy": hora_pico_hoy,
        "tendencia_por_hora": tendencia_por_hora,
        "por_clase_ultimos_5min": por_clase,
    }

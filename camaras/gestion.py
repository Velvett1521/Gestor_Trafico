"""
Motor de gestión de tránsito basado en reglas (no es un modelo entrenado:
es lógica if/then explícita y auditable, a propósito, para que cada
decisión se pueda explicar en una frase).

Idea general: cada cámara de una intersección representa un acceso/carril.
Se compara el ritmo de vehículos/minuto reciente entre los accesos de la
MISMA intersección y se decide cuál necesita más tiempo de luz verde.

Esto es una SIMULACIÓN: no controla semáforos reales, solo calcula qué
tiempos les daría un semáforo inteligente y por qué, para mostrarlo en
la interfaz.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from .analisis import UMBRAL_CONGESTION_POR_MINUTO
from .models import Camara, ConteoVehiculo, DecisionSemaforo, Interseccion

# Tiempos de verde de referencia (segundos) para un ciclo de semáforo
# de dos fases. Son valores de simulación, no una norma de ingeniería
# vial real.
VERDE_BASE = 30
VERDE_MINIMO = 12
VERDE_MAXIMO = 60

# Umbral de diferencia de ritmo (veh/min) a partir del cual vale la pena
# desbalancear los tiempos en vez de dejarlos parejos.
DIFERENCIA_MINIMA_PARA_AJUSTAR = 2.0


@dataclass
class EstadoAcceso:
    camara_id: int
    nombre: str
    ritmo_por_minuto: float
    congestion: bool
    segundos_verde: int = VERDE_BASE
    fase: str = "rojo"  # 'verde' | 'amarillo' | 'rojo', para el semáforo virtual


@dataclass
class DecisionGestion:
    interseccion_id: int
    interseccion_nombre: str
    accesos: list = field(default_factory=list)   # lista de EstadoAcceso
    regla_aplicada: str = "sin_datos"
    justificacion: str = "Aún no hay suficientes datos de tránsito para esta intersección."
    hay_congestion: bool = False


def _ritmo_reciente(camara_id: int, minutos: int = 5) -> float:
    """Vehículos/minuto de una cámara en los últimos `minutos`."""
    desde = timezone.now() - timedelta(minutes=minutos)
    total = (
        ConteoVehiculo.objects
        .filter(camara_id=camara_id, marca_tiempo__gte=desde)
        .aggregate(suma=Sum('cantidad'))['suma'] or 0
    )
    return round(total / minutos, 2)


def _repartir_verde(accesos: list[EstadoAcceso]) -> tuple[str, str]:
    """
    Aplica las reglas de reparto de tiempo de verde sobre una lista de
    accesos (cámaras) de UNA intersección, modificando `segundos_verde`
    y `fase` in-place. Devuelve (regla_aplicada, justificacion).
    """
    if len(accesos) < 2:
        # Con un solo acceso registrado no hay nada que balancear entre
        # carriles; se deja el tiempo base y la fase en verde fijo.
        if accesos:
            accesos[0].fase = "verde"
        return "acceso_unico", (
            "Solo hay una cámara registrada en esta intersección: no hay otro "
            "acceso con el que comparar tráfico, así que se mantiene el tiempo base."
        )

    accesos_ordenados = sorted(accesos, key=lambda a: a.ritmo_por_minuto, reverse=True)
    principal = accesos_ordenados[0]
    resto = accesos_ordenados[1:]
    diferencia = principal.ritmo_por_minuto - resto[0].ritmo_por_minuto

    if principal.congestion and diferencia >= DIFERENCIA_MINIMA_PARA_AJUSTAR:
        # Regla 1: un acceso está congestionado Y claramente por encima
        # de los demás -> se le da el máximo de verde permitido y se
        # recorta el resto al mínimo, para desahogarlo primero.
        principal.segundos_verde = VERDE_MAXIMO
        principal.fase = "verde"
        for acc in resto:
            acc.segundos_verde = VERDE_MINIMO
            acc.fase = "rojo"
        return "priorizar_acceso_congestionado", (
            f'"{principal.nombre}" está en congestión ({principal.ritmo_por_minuto} veh/min, '
            f'{diferencia:.1f} más que el siguiente acceso), así que se le asignan '
            f'{VERDE_MAXIMO}s de verde y se reduce el resto a {VERDE_MINIMO}s para despejarlo.'
        )

    if diferencia >= DIFERENCIA_MINIMA_PARA_AJUSTAR:
        # Regla 2: hay una diferencia notable de tráfico pero sin llegar
        # a congestión -> ajuste proporcional moderado, no al extremo.
        extra = min(15, round(diferencia * 2))
        principal.segundos_verde = VERDE_BASE + extra
        principal.fase = "verde"
        for acc in resto:
            acc.segundos_verde = max(VERDE_MINIMO, VERDE_BASE - extra)
            acc.fase = "rojo"
        return "ajuste_proporcional", (
            f'"{principal.nombre}" tiene {diferencia:.1f} veh/min más que el resto, sin llegar '
            f'a congestión. Se le dan {principal.segundos_verde}s de verde (base {VERDE_BASE}s + '
            f'{extra}s) y se recorta el resto a {VERDE_BASE - extra}s.'
        )

    # Regla 3: tráfico parejo entre accesos -> tiempos base sin ajuste.
    for acc in accesos_ordenados:
        acc.segundos_verde = VERDE_BASE
    principal.fase = "verde"
    for acc in resto:
        acc.fase = "rojo"
    return "trafico_equilibrado", (
        f'El tráfico está repartido de forma pareja entre los accesos '
        f'(diferencia de solo {diferencia:.1f} veh/min), así que se mantienen '
        f'los {VERDE_BASE}s de verde base para todos por igual.'
    )


def evaluar_interseccion(interseccion_id: int) -> DecisionGestion:
    """
    Calcula el estado y la decisión de reparto de semáforo para todas
    las cámaras activas de una intersección, y registra la decisión en
    DecisionSemaforo para trazabilidad.
    """
    interseccion = Interseccion.objects.get(pk=interseccion_id)
    camaras = list(Camara.objects.filter(interseccion_id=interseccion_id, activa=True))

    if not camaras:
        return DecisionGestion(
            interseccion_id=interseccion_id,
            interseccion_nombre=interseccion.nombre,
        )

    accesos = []
    for cam in camaras:
        ritmo = _ritmo_reciente(cam.id)
        accesos.append(EstadoAcceso(
            camara_id=cam.id,
            nombre=cam.nombre,
            ritmo_por_minuto=ritmo,
            congestion=ritmo >= UMBRAL_CONGESTION_POR_MINUTO,
        ))

    regla, justificacion = _repartir_verde(accesos)
    hay_congestion = any(a.congestion for a in accesos)

    decision = DecisionGestion(
        interseccion_id=interseccion_id,
        interseccion_nombre=interseccion.nombre,
        accesos=accesos,
        regla_aplicada=regla,
        justificacion=justificacion,
        hay_congestion=hay_congestion,
    )

    # Bitácora: solo tiene sentido registrar una decisión de reparto si
    # hubo más de un acceso comparado (con uno solo no hay "favorecida").
    if len(accesos) >= 2:
        favorecida = max(accesos, key=lambda a: a.segundos_verde)
        resto_segundos = min(a.segundos_verde for a in accesos if a is not favorecida)
        DecisionSemaforo.objects.create(
            interseccion_id=interseccion_id,
            camara_favorecida_id=favorecida.camara_id,
            segundos_verde_favorecida=favorecida.segundos_verde,
            segundos_verde_resto=resto_segundos,
            regla_aplicada=regla,
            justificacion=justificacion,
        )

    return decision


def decision_a_dict(decision: DecisionGestion) -> dict:
    """Serializa una DecisionGestion a dict plano para JsonResponse."""
    return {
        "interseccion_id": decision.interseccion_id,
        "interseccion_nombre": decision.interseccion_nombre,
        "regla_aplicada": decision.regla_aplicada,
        "justificacion": decision.justificacion,
        "hay_congestion": decision.hay_congestion,
        "accesos": [
            {
                "camara_id": a.camara_id,
                "nombre": a.nombre,
                "ritmo_por_minuto": a.ritmo_por_minuto,
                "congestion": a.congestion,
                "segundos_verde": a.segundos_verde,
                "fase": a.fase,
            }
            for a in decision.accesos
        ],
    }

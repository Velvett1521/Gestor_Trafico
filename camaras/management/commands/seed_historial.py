"""
Genera datos simulados en ConteoVehiculo (y opcionalmente DecisionSemaforo)
para poder ver el historial, el análisis de congestión y el semáforo
virtual funcionando sin esperar horas de tráfico real.

Simula un patrón realista: más vehículos en horas pico (7-9am, 1-2pm,
6-8pm hora local), menos de madrugada, variación por clase de vehículo,
y ruido aleatorio para que no se vea una línea perfecta. Respeta el
esquema actual del proyecto (ConteoVehiculo con marca_tiempo/clase, no
ConteoVehicular con minuto/tipo_vehiculo de una versión anterior).

Uso:
    python manage.py seed_historial
    python manage.py seed_historial --dias 3
    python manage.py seed_historial --interseccion 1 --limpiar
    python manage.py seed_historial --crear-demo     # crea intersección + cámaras si no hay ninguna
    python manage.py seed_historial --con-decisiones # además siembra bitácora de DecisionSemaforo
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from camaras.models import Interseccion, Camara, ConteoVehiculo, DecisionSemaforo
from camaras.analisis import UMBRAL_CONGESTION_POR_MINUTO
from camaras.gestion import VERDE_BASE, VERDE_MINIMO, VERDE_MAXIMO

# Pesos relativos por clase de vehículo (deben coincidir con las claves que
# usa deteccion.py: CLASES_VEHICULOS = {bicicleta, auto, moto, autobus, camion}).
PESOS_VEHICULO = {
    'auto': 0.58,
    'moto': 0.19,
    'camion': 0.06,
    'autobus': 0.04,
    'bicicleta': 0.13,
}


def factor_hora(hora):
    """
    Multiplicador de tráfico (0.08 a 1.0) según la hora del día, con picos
    en horario escolar/laboral típico de México (7:30am, 2pm, 7pm).
    """
    picos = [7.5, 14, 19]
    mejor = max(
        1.0 - min(abs(hora - p), 24 - abs(hora - p)) / 3.0
        for p in picos
    )
    base_nocturna = 0.08 if hora < 5 or hora >= 23 else 0.25
    return max(base_nocturna, mejor)


class Command(BaseCommand):
    help = (
        'Genera conteos vehiculares simulados en ConteoVehiculo (y opcionalmente '
        'DecisionSemaforo) para ver el historial y el análisis sin esperar datos reales.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=7, help='Días hacia atrás a simular (default: 7).')
        parser.add_argument('--interseccion', type=int, default=None, help='ID de una intersección específica; si se omite, usa todas.')
        parser.add_argument('--camara', type=int, default=None, help='ID de una cámara específica; si se omite, usa todas las activas.')
        parser.add_argument('--vehiculos-pico', type=int, default=28, help='Vehículos aprox. por minuto en hora pico, por cámara (default: 28).')
        parser.add_argument('--limpiar', action='store_true', help='Borra el historial simulado previo (ConteoVehiculo y DecisionSemaforo) de las cámaras/intersecciones afectadas antes de generar.')
        parser.add_argument('--crear-demo', action='store_true', help='Si no hay intersecciones/cámaras, crea una intersección con 4 cámaras de ejemplo.')
        parser.add_argument('--con-decisiones', action='store_true', help='Además de ConteoVehiculo, genera una bitácora de DecisionSemaforo usando el motor de reglas real (camaras.gestion).')
        parser.add_argument('--semilla', type=int, default=None, help='Semilla aleatoria para resultados reproducibles.')

    def handle(self, *args, **opciones):
        if opciones['semilla'] is not None:
            random.seed(opciones['semilla'])

        camaras = self._resolver_camaras(opciones)
        if not camaras:
            self.stdout.write(self.style.ERROR(
                'No hay cámaras para sembrar. Crea una intersección y cámaras en /admin/, '
                'o vuelve a correr con --crear-demo.'
            ))
            return

        if opciones['limpiar']:
            borrados_conteo, _ = ConteoVehiculo.objects.filter(camara__in=camaras).delete()
            intersecciones_afectadas = {c.interseccion_id for c in camaras}
            borrados_decision, _ = DecisionSemaforo.objects.filter(
                interseccion_id__in=intersecciones_afectadas
            ).delete()
            self.stdout.write(self.style.WARNING(
                f'Historial previo borrado: {borrados_conteo} conteos, {borrados_decision} decisiones de semáforo.'
            ))

        total_filas = 0
        for camara in camaras:
            filas = self._sembrar_camara(camara, opciones['dias'], opciones['vehiculos_pico'])
            total_filas += filas
            self.stdout.write(f'  {camara} -> {filas} minutos con datos')

        self.stdout.write(self.style.SUCCESS(
            f'Listo: {total_filas} filas-minuto generadas para {len(camaras)} cámara(s) '
            f'en los últimos {opciones["dias"]} día(s).'
        ))
        if not opciones['limpiar']:
            self.stdout.write(
                'Nota: sin --limpiar, los minutos que ya existían no se duplican '
                '(se ignoran); correr el comando de nuevo más tarde solo rellena '
                'los minutos nuevos desde la última corrida hasta ahora.'
            )

        if opciones['con_decisiones']:
            self._sembrar_decisiones(camaras)

    def _resolver_camaras(self, opciones):
        if opciones['camara']:
            return list(Camara.objects.filter(pk=opciones['camara']))

        qs = Camara.objects.filter(activa=True)
        if opciones['interseccion']:
            qs = qs.filter(interseccion_id=opciones['interseccion'])

        camaras = list(qs)
        if camaras:
            return camaras

        if opciones['crear_demo']:
            return self._crear_demo()

        return []

    def _crear_demo(self):
        interseccion = Interseccion.objects.create(
            nombre='Av. Juárez y 5 de Mayo (demo)',
            latitud=19.0433, longitud=-98.2000,
        )
        nombres = ['Cam Norte', 'Cam Sur', 'Cam Este', 'Cam Oeste']
        camaras = [
            Camara.objects.create(interseccion=interseccion, nombre=n, tipo='local')
            for n in nombres
        ]
        self.stdout.write(self.style.SUCCESS(f'Creada intersección demo "{interseccion}" con {len(camaras)} cámaras.'))
        return camaras

    @transaction.atomic
    def _sembrar_camara(self, camara, dias, vehiculos_pico):
        ahora = timezone.now().replace(second=0, microsecond=0)
        inicio = ahora - timedelta(days=dias)

        # Cada cámara tiene un nivel base ligeramente distinto (no todas las
        # vialidades tienen el mismo flujo), así el historial no se ve
        # idéntico entre cámaras de la misma intersección.
        factor_camara = random.uniform(0.7, 1.15)

        filas_a_crear = []
        minuto = inicio
        while minuto <= ahora:
            # minuto está en UTC internamente (USE_TZ=True); el patrón de
            # horas pico debe calcularse en hora local, igual que hace
            # analisis.py/deteccion.py con timezone.localtime(), o el
            # patrón queda desfasado varias horas respecto al horario real.
            local = timezone.localtime(minuto)
            intensidad = factor_hora(local.hour + local.minute / 60) * factor_camara

            ruido = random.uniform(0.6, 1.3)
            esperado = vehiculos_pico * intensidad * ruido
            vehiculos_este_minuto = max(0, round(random.gauss(esperado, esperado * 0.3 + 0.5)))

            if vehiculos_este_minuto > 0:
                por_clase = self._repartir_por_clase(vehiculos_este_minuto)
                for clase, cantidad in por_clase.items():
                    if cantidad > 0:
                        filas_a_crear.append(ConteoVehiculo(
                            camara=camara, marca_tiempo=minuto,
                            clase=clase, cantidad=cantidad,
                        ))

            minuto += timedelta(minutes=1)

        # bulk_create respeta el UniqueConstraint (camara, marca_tiempo, clase);
        # ignore_conflicts evita tronar si ya existían filas de una corrida
        # previa sin --limpiar.
        ConteoVehiculo.objects.bulk_create(filas_a_crear, batch_size=500, ignore_conflicts=True)
        return len({f.marca_tiempo for f in filas_a_crear})

    @staticmethod
    def _repartir_por_clase(total):
        """Reparte `total` vehículos entre clases según PESOS_VEHICULO, con
        muestreo aleatorio ponderado para que no sea siempre la misma proporción."""
        clases = list(PESOS_VEHICULO.keys())
        pesos = list(PESOS_VEHICULO.values())
        resultado = {c: 0 for c in clases}
        for _ in range(total):
            elegido = random.choices(clases, weights=pesos, k=1)[0]
            resultado[elegido] += 1
        return resultado

    def _sembrar_decisiones(self, camaras):
        """
        Genera una bitácora de DecisionSemaforo usando el motor de reglas
        REAL (camaras.gestion._repartir_verde), no una copia simulada de la
        lógica, para que la pantalla de "gestión" tenga datos de ejemplo
        que sean consistentes con lo que el sistema calcularía en vivo.
        """
        from camaras.gestion import EstadoAcceso, _repartir_verde

        intersecciones = {c.interseccion for c in camaras}
        total_decisiones = 0
        ahora = timezone.now()

        for interseccion in intersecciones:
            camaras_interseccion = [c for c in camaras if c.interseccion_id == interseccion.id]
            if len(camaras_interseccion) < 2:
                continue  # el motor de reglas no compara con un solo acceso

            # Una decisión de ejemplo cada ~10 minutos en las últimas 2 horas,
            # usando ritmos simulados (no se recalculan desde ConteoVehiculo
            # para no acoplar el seed a la ventana de tiempo exacta del motor).
            for i in range(12):
                momento = ahora - timedelta(minutes=10 * i)
                accesos = [
                    EstadoAcceso(
                        camara_id=cam.id,
                        nombre=cam.nombre,
                        ritmo_por_minuto=round(random.uniform(1, UMBRAL_CONGESTION_POR_MINUTO * 1.8), 2),
                        congestion=False,
                    )
                    for cam in camaras_interseccion
                ]
                for acc in accesos:
                    acc.congestion = acc.ritmo_por_minuto >= UMBRAL_CONGESTION_POR_MINUTO

                regla, justificacion = _repartir_verde(accesos)
                favorecida = max(accesos, key=lambda a: a.segundos_verde)
                resto_segundos = min(a.segundos_verde for a in accesos if a is not favorecida)

                decision = DecisionSemaforo.objects.create(
                    interseccion=interseccion,
                    camara_favorecida_id=favorecida.camara_id,
                    segundos_verde_favorecida=favorecida.segundos_verde,
                    segundos_verde_resto=resto_segundos,
                    regla_aplicada=regla,
                    justificacion=justificacion,
                )
                # marca_tiempo es auto_now_add; se ajusta después para que
                # la bitácora quede repartida en el tiempo, no toda "ahora".
                DecisionSemaforo.objects.filter(pk=decision.pk).update(marca_tiempo=momento)
                total_decisiones += 1

        self.stdout.write(self.style.SUCCESS(f'Bitácora simulada: {total_decisiones} decisiones de semáforo generadas.'))

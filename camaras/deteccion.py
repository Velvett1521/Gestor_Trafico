"""
Carga y ejecución de YOLO + tracking para detección y CONTEO de
vehículos únicos que cruzan una línea virtual frente a la cámara.

Flujo por frame:
  1. YOLO detecta vehículos (igual que antes).
  2. ByteTrack (integrado en ultralytics) asigna un ID persistente a
     cada vehículo mientras siga visible entre frames.
  3. Se compara el centro de cada caja contra su posición en el frame
     anterior: si cruzó la línea virtual, se cuenta UNA vez (por ID) y
     no se vuelve a contar aunque el ID lo siga viendo cruzada.
  4. Los cruces se acumulan y cada cierto intervalo se "vacían" a la
     base de datos como registros agregados por minuto (ConteoVehiculo),
     que es lo que alimenta el análisis histórico.
"""
import io
import threading
import time
from collections import defaultdict

from django.utils import timezone
from PIL import Image

_lock = threading.Lock()
# Una instancia de YOLO POR CÁMARA: ultralytics guarda el estado del tracker
# (ByteTrack) dentro del propio modelo cuando se usa persist=True, así que
# compartir una sola instancia mezclaría los IDs entre cámaras. Cada una
# también tiene su lock, porque el servidor atiende requests en paralelo y
# dos frames de la MISMA cámara no deben entrar al tracker a la vez.
_modelos = {}          # {camara_id: YOLO}
_locks_camara = {}     # {camara_id: threading.Lock}

# Nombre del checkpoint de Ultralytics. Se descarga solo la primera vez
# que se instancia YOLO(...) y se guarda en caché local.
# Si la latencia sigue siendo un problema, cambia a "yolov8n.pt" (nano):
# es ~3x más rápido que "s" y con vehículos grandes/cercanos como los que
# ve una cámara de cruce, la pérdida de precisión suele ser mínima.
NOMBRE_MODELO = "yolov8s.pt"

# Tamaño (lado) al que se reescala la imagen antes de pasarla al modelo.
TAMANO_INFERENCIA = 960

# IDs de clases COCO que nos interesan (vehículos).
CLASES_VEHICULOS = {1: "bicicleta", 2: "auto", 3: "moto", 5: "autobus", 7: "camion"}

UMBRAL_CONFIANZA = 0.35

# --- Estado de tracking por cámara -----------------------------------
# Cada cámara tiene su propio tracker y su propia "memoria" de qué lado
# de la línea estaba cada ID la última vez que se vio, para poder
# detectar el cruce (cambio de lado) y no perder el estado entre
# requests HTTP independientes (cada request es sin estado por sí solo).
_lado_previo_por_id = defaultdict(dict)   # {camara_id: {track_id: lado ('arriba'/'abajo')}}
_ids_contados = defaultdict(set)          # {camara_id: {track_id, ...}} ya contados, evita doble conteo
_buffer_conteos = defaultdict(lambda: defaultdict(int))  # {camara_id: {clase: cantidad pendiente de guardar}}
_buffer_lock = threading.Lock()


def _detectar_dispositivo() -> str:
    """Elige el mejor dispositivo disponible: GPU NVIDIA (cuda), GPU de
    Mac (mps) o, si no hay ninguna, cpu."""
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _obtener_modelo(camara_id: int):
    """Devuelve (modelo, lock) exclusivos de la cámara indicada."""
    with _lock:
        if camara_id not in _modelos:
            from ultralytics import YOLO
            modelo = YOLO(NOMBRE_MODELO)
            modelo.to(_detectar_dispositivo())
            _modelos[camara_id] = modelo
            _locks_camara[camara_id] = threading.Lock()
        return _modelos[camara_id], _locks_camara[camara_id]


def _lado_de_linea(cy: float, alto_imagen: int, linea_y_frac: float) -> str:
    """Devuelve 'arriba' o 'abajo' según en qué lado de la línea
    horizontal (a linea_y_frac del alto total) cae el centro Y de la caja."""
    return "arriba" if cy < alto_imagen * linea_y_frac else "abajo"


def procesar_frame(camara_id: int, bytes_imagen: bytes, linea_y_frac: float = 0.5) -> dict:
    """
    Corre YOLO+tracking sobre un frame y actualiza el conteo de cruces
    de la cámara indicada.

    Devuelve:
        {
          "detecciones": [{"id": 4, "clase": "auto", "confianza": 0.9,
                            "x1":.., "y1":.., "x2":.., "y2":..}, ...],
          "cruces_nuevos": 2,          # vehículos que cruzaron en ESTE frame
          "total_sesion": 37,          # acumulado desde que se inició el conteo
        }
    """
    t0 = time.perf_counter()
    modelo, lock_camara = _obtener_modelo(camara_id)
    imagen = Image.open(io.BytesIO(bytes_imagen)).convert("RGB")
    alto_imagen = imagen.height
    t1 = time.perf_counter()

    # persist=True mantiene el estado del tracker (ByteTrack) entre
    # llamadas. Como cada cámara tiene su propia instancia de modelo
    # (ver _obtener_modelo), los IDs de una cámara nunca se mezclan con
    # los de otra.
    with lock_camara:
        resultados = modelo.track(
            imagen,
            verbose=False,
            conf=UMBRAL_CONFIANZA,
            classes=list(CLASES_VEHICULOS.keys()),
            imgsz=TAMANO_INFERENCIA,
            quantize=(16 if modelo.device.type == "cuda" else None),  # antes: half=... (deprecado en ultralytics >= 8.4)
            persist=True,
            tracker="bytetrack.yaml",
        )
    t2 = time.perf_counter()

    detecciones = []
    cruces_nuevos = 0
    lado_previo = _lado_previo_por_id[camara_id]
    ids_contados = _ids_contados[camara_id]

    for resultado in resultados:
        cajas = resultado.boxes
        if cajas.id is None:
            continue  # el tracker aún no asignó IDs (primeros frames)
        for caja, track_id in zip(cajas, cajas.id.tolist()):
            track_id = int(track_id)
            clase_id = int(caja.cls[0])
            clase = CLASES_VEHICULOS.get(clase_id, str(clase_id))
            x1, y1, x2, y2 = caja.xyxy[0].tolist()
            cy = (y1 + y2) / 2

            lado_actual = _lado_de_linea(cy, alto_imagen, linea_y_frac)
            lado_anterior = lado_previo.get(track_id)
            lado_previo[track_id] = lado_actual

            cruzo = (
                lado_anterior is not None
                and lado_anterior != lado_actual
                and track_id not in ids_contados
            )
            if cruzo:
                ids_contados.add(track_id)
                cruces_nuevos += 1
                with _buffer_lock:
                    _buffer_conteos[camara_id][clase] += 1

            detecciones.append({
                "id": track_id,
                "clase": clase,
                "confianza": round(float(caja.conf[0]), 3),
                "x1": round(x1), "y1": round(y1),
                "x2": round(x2), "y2": round(y2),
                "cruzo": cruzo,
            })

    # Limpieza simple: si un track_id lleva mucho tiempo sin aparecer,
    # ByteTrack ya lo habrá descartado; para no crecer sin límite,
    # recortamos el diccionario cuando se pone grande.
    if len(lado_previo) > 500:
        vistos_ahora = {d["id"] for d in detecciones}
        for tid in list(lado_previo.keys()):
            if tid not in vistos_ahora:
                lado_previo.pop(tid, None)

    t3 = time.perf_counter()
    print(
        f"[YOLO] decode={1000*(t1-t0):.1f}ms  "
        f"inferencia+track={1000*(t2-t1):.1f}ms  "
        f"empaquetado={1000*(t3-t2):.1f}ms  "
        f"total_backend={1000*(t3-t0):.1f}ms  "
        f"cruces_nuevos={cruces_nuevos}"
    )

    return {
        "detecciones": detecciones,
        "cruces_nuevos": cruces_nuevos,
        "total_sesion": len(ids_contados),
    }


def volcar_buffer_a_bd():
    """
    Guarda en ConteoVehiculo lo acumulado en memoria desde el último
    volcado, agregado por minuto. Se llama periódicamente (ver la vista
    `estado_conteo` o un comando/cron) para no golpear la base de datos
    en cada frame.
    """
    from .models import ConteoVehiculo, Camara

    with _buffer_lock:
        pendientes = {cid: dict(clases) for cid, clases in _buffer_conteos.items() if clases}
        _buffer_conteos.clear()

    if not pendientes:
        return 0

    # IMPORTANTE: timezone.now() (aware), no datetime.now() (naive). Con
    # USE_TZ=True, Django guarda un datetime naive asumiendo que ya está
    # en UTC; como TIME_ZONE es America/Mexico_City (UTC-6), un naive
    # quedaba desfasado 6h al leerlo de vuelta, rompiendo toda
    # comparación de "mismo horario" contra el histórico.
    marca_minuto = timezone.now().replace(second=0, microsecond=0)
    guardados = 0
    for camara_id, clases in pendientes.items():
        if not Camara.objects.filter(pk=camara_id).exists():
            continue
        for clase, cantidad in clases.items():
            registro, _creado = ConteoVehiculo.objects.get_or_create(
                camara_id=camara_id, marca_tiempo=marca_minuto, clase=clase,
                defaults={"cantidad": 0},
            )
            registro.cantidad += cantidad
            registro.save(update_fields=["cantidad"])
            guardados += 1
    return guardados


def reiniciar_conteo(camara_id: int):
    """Reinicia el conteo de sesión de una cámara (botón 'reiniciar conteo' en la UI)."""
    _lado_previo_por_id.pop(camara_id, None)
    _ids_contados.pop(camara_id, None)
    # Reinicia también el tracker de esa cámara (IDs vuelven a empezar).
    modelo = _modelos.get(camara_id)
    predictor = getattr(modelo, 'predictor', None) if modelo else None
    for tracker in getattr(predictor, 'trackers', None) or []:
        try:
            tracker.reset()
        except Exception:  # noqa: BLE001 - no es crítico si esta versión no lo soporta
            pass
    with _buffer_lock:
        _buffer_conteos.pop(camara_id, None)




# ---------------------------------------------------------------------
# Volcador periódico a BD.
#
# ANTES: el consumer llamaba a volcar_buffer_a_bd() en CADA frame.
# Con 4 cámaras a 10 fps, eso son 40 llamadas por segundo al thread pool
# de asgiref, cada una tomando el GIL para hacer INSERT/UPDATE. El hilo
# que decodifica el JPEG del siguiente frame se quedaba esperando, y por
# eso aparecían picos de decode=400ms cuando lo normal es 5-15ms.
#
# AHORA: un solo hilo daemon escribe cada N segundos. No compite con
# los frames, no satura el thread pool, y agrupa más filas por escritura
# (menos round-trips a Postgres).
# ---------------------------------------------------------------------
import threading as _threading
import time as _time

_INTERVALO_VOLCADO_SEG = 5
_hilo_volcador_iniciado = False
_lock_arranque_volcador = _threading.Lock()


def _bucle_volcador():
    while True:
        _time.sleep(_INTERVALO_VOLCADO_SEG)
        try:
            n = volcar_buffer_a_bd()
            if n:
                print(f"[volcador] {n} filas guardadas")
        except Exception as exc:
            print(f"[volcador] error: {exc}")


def arrancar_volcador():
    """Arranca el hilo daemon una sola vez (idempotente)."""
    global _hilo_volcador_iniciado
    with _lock_arranque_volcador:
        if _hilo_volcador_iniciado:
            return
        hilo = _threading.Thread(target=_bucle_volcador, daemon=True, name="volcador-conteos")
        hilo.start()
        _hilo_volcador_iniciado = True
        print("[volcador] hilo de volcado periódico iniciado.")

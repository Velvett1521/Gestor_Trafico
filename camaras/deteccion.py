"""
Carga y ejecución del modelo YOLO para detección de vehículos.

El modelo se carga UNA sola vez por proceso (patrón singleton) para no
pagar el costo de inicialización en cada request. Con el servidor de
desarrollo de Django (runserver) esto es un solo proceso; en producción,
con varios workers (gunicorn/uwsgi), cada worker cargará su propia copia
en memoria la primera vez que reciba una petición.
"""
import io
import threading

from PIL import Image

_lock = threading.Lock()
_modelo = None

# Nombre del checkpoint de Ultralytics. Se descarga solo la primera vez
# que se instancia YOLO(...) y se guarda en caché local.
NOMBRE_MODELO = "yolov8s.pt"

# IDs de clases COCO que nos interesan (vehículos). YOLOv8 viene
# preentrenado en COCO con estos índices:
#   2: car, 3: motorcycle, 5: bus, 7: truck
# Se incluye bicycle (1) porque en cruces urbanos suele ser relevante,
# quítalo del set si solo quieres motorizados.
CLASES_VEHICULOS = {1: "bicicleta", 2: "auto", 3: "moto", 5: "autobus", 7: "camion"}

UMBRAL_CONFIANZA = 0.35


def _obtener_modelo():
    global _modelo
    if _modelo is None:
        with _lock:
            if _modelo is None:  # doble check dentro del lock
                from ultralytics import YOLO
                _modelo = YOLO(NOMBRE_MODELO)
    return _modelo


def detectar_vehiculos(bytes_imagen: bytes) -> list[dict]:
    """
    Recibe los bytes crudos de una imagen (JPEG/PNG), corre YOLO y
    devuelve una lista de detecciones de vehículos:

        [{"clase": "auto", "confianza": 0.87,
          "x1": 120, "y1": 45, "x2": 340, "y2": 210}, ...]

    Las coordenadas son píxeles absolutos sobre la imagen recibida.
    """
    modelo = _obtener_modelo()
    imagen = Image.open(io.BytesIO(bytes_imagen)).convert("RGB")

    resultados = modelo.predict(
        imagen,
        verbose=False,
        conf=UMBRAL_CONFIANZA,
        classes=list(CLASES_VEHICULOS.keys()),
    )

    detecciones = []
    for resultado in resultados:
        for caja in resultado.boxes:
            clase_id = int(caja.cls[0])
            x1, y1, x2, y2 = caja.xyxy[0].tolist()
            detecciones.append({
                "clase": CLASES_VEHICULOS.get(clase_id, str(clase_id)),
                "confianza": round(float(caja.conf[0]), 3),
                "x1": round(x1), "y1": round(y1),
                "x2": round(x2), "y2": round(y2),
            })
    return detecciones

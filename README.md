# Gestor de Tráfico (fase 1: visor de cámara)

Proyecto Django que accede a la cámara del dispositivo desde el navegador.
La IA de gestión de tráfico se integra en una fase posterior.

## Instalación

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations camaras
python manage.py migrate
python manage.py createsuperuser   # opcional, para /admin
python manage.py runserver
```

Abre http://127.0.0.1:8000 y acepta el permiso de cámara.

## Importante

`getUserMedia` solo funciona en `localhost` o HTTPS. Si abres el sitio desde
otro dispositivo por IP (http://192.168.x.x:8000) el navegador bloqueará la
cámara; usa HTTPS (runserver_plus + certificado) o un túnel como ngrok.

## Estructura

- `camaras/templates/camaras/monitor.html`: visor, selector de cámara, FPS, capturas.
  El `<canvas id="overlay">` y el `bucleFrames()` son los puntos de enganche para la IA.
- `camaras/models.py`: `Interseccion` y `Camara` (ya listos para cámaras IP/RTSP).

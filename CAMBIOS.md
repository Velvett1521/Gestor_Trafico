# Cambios aplicados (arreglo de errores + seed)

## Errores corregidos

1. **Faltaba `lap` como dependencia.** `/detectar/` tronaba con
   `No module named 'lap'` porque ByteTrack (el tracker que usa
   `camaras/deteccion.py` vía `ultralytics`) lo necesita y no estaba
   declarado en ningún lado. Agregado a `requirements.txt`.

2. **No existía `requirements.txt`.** Sin él no hay forma de reproducir
   el entorno (así pasó con `lap`: nadie sabía que hacía falta hasta que
   tronó en producción). Creado con las dependencias reales que usa el
   código: Django, ultralytics, lap, Pillow.

3. **`half=...` deprecado en `camaras/deteccion.py`.** Ultralytics 8.4+
   movió ese parámetro a `quantize` (`half=True` → `quantize=16`,
   `half=False` → `quantize=None`). Generaba un warning en cada frame
   procesado y en una versión futura de ultralytics dejará de funcionar
   del todo. Corregido.

4. **`camaras/consumers.py` era código muerto y roto.** Era un
   WebSocket consumer de una arquitectura anterior (Channels), de
   cuando el proyecto todavía no tenía `analisis.py`/`gestion.py`.
   Importaba `camaras.ia.detector` (carpeta que ya no existe) y
   `ConteoVehicular` (modelo que ya se renombró a `ConteoVehiculo`).
   Nadie lo importa en el flujo actual (no hay `asgi.py`, `routing.py`,
   ni Channels en `INSTALLED_APPS`), así que no rompía nada en
   ejecución, pero sí truena si algo llega a importarlo. Eliminado.

5. **Faltaban `camaras/management/__init__.py` y
   `camaras/management/commands/__init__.py`.** Sin ellos Django no
   reconoce el paquete de comandos (`python manage.py seed_historial`
   fallaba con "Unknown command"). Recreados.

## Qué NO se tocó

- La lógica de detección, tracking y conteo de cruces (`deteccion.py`)
  se probó de extremo a extremo (con YOLO mockeado, para no depender de
  una imagen real) y el conteo de cruces funciona correctamente: cuenta
  una sola vez por vehículo, en el frame exacto donde cruza la línea.
- El análisis histórico (`analisis.py`) y el motor de semáforos
  (`gestion.py`) ya traían el fix del "-96%" (dividir entre minutos con
  dato real, no ventana fija) aplicado correctamente — se dejó igual.
- El HTML/JS del template se revisó línea por línea: sintaxis válida,
  todos los `getElementById` tienen su `id` correspondiente en el HTML,
  y el flujo de endpoints (`/detectar/`, `/analisis/`, `/gestion/`,
  `/alertas/`, `/reiniciar/`) está bien conectado. No se encontraron
  errores ahí.

## Seed de datos simulados

`camaras/management/commands/seed_historial.py` genera historial
realista en `ConteoVehiculo` (patrón de horas pico en hora local) y,
opcionalmente, bitácora de `DecisionSemaforo` usando el motor de reglas
real del proyecto.

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_historial --dias 7 --crear-demo --con-decisiones
python manage.py runserver
```

Ver `python manage.py seed_historial --help` para todas las opciones.

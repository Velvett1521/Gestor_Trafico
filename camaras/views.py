from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse

from .deteccion import procesar_frame, volcar_buffer_a_bd, reiniciar_conteo
from .analisis import analizar_camara
from .gestion import evaluar_interseccion, decision_a_dict
from .models import Camara, Interseccion


def monitor(request):
    camaras = Camara.objects.select_related('interseccion').filter(activa=True)
    return render(request, 'camaras/monitor.html', {'camaras': camaras})


@csrf_exempt  # el frame se manda desde JS con fetch; se valida por otros medios en producción
@require_POST
def detectar(request):
    """
    Recibe un frame de video como archivo multipart ("frame") más el ID
    de la cámara ("camara_id"), corre YOLO+tracking y devuelve las
    detecciones junto con el conteo de vehículos que cruzaron la línea
    virtual en este frame.
    """
    archivo = request.FILES.get('frame')
    if archivo is None:
        return JsonResponse({'error': 'No se recibió ningún frame ("frame").'}, status=400)

    camara_id = request.POST.get('camara_id')
    if not camara_id:
        return JsonResponse({'error': 'Falta "camara_id".'}, status=400)

    try:
        camara_id = int(camara_id)
    except ValueError:
        return JsonResponse({'error': '"camara_id" debe ser numérico.'}, status=400)

    linea_y_frac = float(request.POST.get('linea_y_frac', 0.5))

    try:
        resultado = procesar_frame(camara_id, archivo.read(), linea_y_frac)
    except Exception as exc:  # noqa: BLE001 - reportamos cualquier fallo del modelo al cliente
        return JsonResponse({'error': f'Error al procesar el frame: {exc}'}, status=500)

    # Volcado del buffer en memoria a BD. Es barato si no hay nada
    # pendiente, así que se puede llamar en cada request sin problema;
    # si se vuelve costoso, mover a un hilo periódico o a un comando
    # `manage.py` corrido por cron cada minuto.
    volcar_buffer_a_bd()

    return JsonResponse(resultado)


@require_POST
def reiniciar(request, camara_id):
    """Reinicia el conteo de sesión de una cámara (botón en la UI)."""
    get_object_or_404(Camara, pk=camara_id)
    reiniciar_conteo(camara_id)
    return JsonResponse({'ok': True})


@require_GET
def analisis(request, camara_id):
    """Devuelve el panorama de tránsito (histórico, congestión, tendencia) de una cámara."""
    get_object_or_404(Camara, pk=camara_id)
    return JsonResponse(analizar_camara(camara_id))


@require_GET
def gestion_interseccion(request, interseccion_id):
    """
    Devuelve la decisión del motor de reglas (semáforo virtual) para
    todas las cámaras activas de una intersección.
    """
    get_object_or_404(Interseccion, pk=interseccion_id)
    decision = evaluar_interseccion(interseccion_id)
    return JsonResponse(decision_a_dict(decision))


@require_GET
def alertas(request):
    """
    Revisa TODAS las cámaras activas y devuelve las que están en
    congestión ahora mismo, para el sistema de notificaciones en la UI.
    Se hace en un único endpoint (en vez de que el cliente pregunte
    cámara por cámara) para no multiplicar requests cuando hay varias
    cámaras registradas.
    """
    resultado = []
    for cam in Camara.objects.select_related('interseccion').filter(activa=True):
        a = analizar_camara(cam.id)
        if a['congestion']:
            resultado.append({
                "camara_id": cam.id,
                "camara_nombre": cam.nombre,
                "interseccion_id": cam.interseccion_id,
                "interseccion_nombre": cam.interseccion.nombre,
                "ritmo_por_minuto": a['ritmo_por_minuto'],
                "variacion_pct": a['variacion_pct'],
            })
    return JsonResponse({"alertas": resultado})

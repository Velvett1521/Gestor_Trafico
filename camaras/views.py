import json

from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from .deteccion import detectar_vehiculos


def monitor(request):
    return render(request, 'camaras/monitor.html')


@csrf_exempt  # el frame se manda desde JS con fetch; se valida por otros medios en producción
@require_POST
def detectar(request):
    """
    Recibe un frame de video como archivo multipart ("frame") y devuelve
    las detecciones de vehículos encontradas por YOLO en formato JSON.
    """
    archivo = request.FILES.get('frame')
    if archivo is None:
        return JsonResponse({'error': 'No se recibió ningún frame ("frame").'}, status=400)

    try:
        detecciones = detectar_vehiculos(archivo.read())
    except Exception as exc:  # noqa: BLE001 - queremos reportar cualquier fallo del modelo al cliente
        return JsonResponse({'error': f'Error al procesar el frame: {exc}'}, status=500)

    return JsonResponse({'detecciones': detecciones})

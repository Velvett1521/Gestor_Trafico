import json
import threading

import numpy as np
import cv2
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async

from .ia.detector import obtener_detector
from .ia.conteo import ContadorLinea
from .models import Camara, ConteoVehicular


class RegistroContadores:
    """
    Mantiene un ContadorLinea por cámara (no por conexión WebSocket).

    Este es el fix del "-96%" en el historial: antes, self.contador vivía en
    el consumer y se reiniciaba en cada connect(). Si el navegador se
    desconectaba un instante (cambio de red, recarga, pestaña en segundo
    plano) el conteo acumulado se perdía y el historial mostraba una caída
    brusca que nunca ocurrió en la realidad. Aquí el contador persiste
    mientras el proceso del servidor siga vivo, indexado por camara_id, así
    que una reconexión del mismo cliente retoma el mismo contador en vez de
    crear uno nuevo en ceros.
    """
    _lock = threading.Lock()
    _contadores = {}  # camara_id -> ContadorLinea

    @classmethod
    def obtener(cls, camara_id, a=(0.0, 0.55), b=(1.0, 0.55)):
        with cls._lock:
            if camara_id not in cls._contadores:
                cls._contadores[camara_id] = ContadorLinea(a, b)
            return cls._contadores[camara_id]

    @classmethod
    def reiniciar(cls, camara_id, a=None, b=None):
        with cls._lock:
            actual = cls._contadores.get(camara_id)
            nuevo_a = a or (actual.a if actual else (0.0, 0.55))
            nuevo_b = b or (actual.b if actual else (1.0, 0.55))
            cls._contadores[camara_id] = ContadorLinea(nuevo_a, nuevo_b)
            return cls._contadores[camara_id]


class TraficoConsumer(AsyncWebsocketConsumer):
    """
    Protocolo:
      cliente -> servidor (texto JSON): {"tipo": "identificar", "camara_id": N}
                                        (obligatorio antes de enviar video;
                                         N es el id de un registro Camara)
      cliente -> servidor (bytes): frame JPEG
      cliente -> servidor (texto JSON): {"tipo": "linea", "a": [x,y], "b": [x,y]}
                                        {"tipo": "reiniciar"}
      servidor -> cliente (texto JSON): {"tipo": "resultado", ...detecciones, conteo, contador}

    Cada cámara reporta de forma independiente. Varias cámaras pueden estar
    conectadas a la vez, cada una con su propio camara_id, y cada una
    persiste su historial por separado: así se modela una intersección real
    con varios accesos/carriles, cada uno con su cámara.
    """

    async def connect(self):
        self.camara_id = None
        self.contador = None
        self.ocupado = False  # descarta frames si el anterior sigue procesándose
        await self.accept()
        await self.send(text_data=json.dumps({'tipo': 'listo'}))

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            await self._mensaje_control(text_data)
            return

        if self.camara_id is None:
            await self.send(text_data=json.dumps({
                'tipo': 'error',
                'detalle': 'Envía primero {"tipo":"identificar","camara_id":N} antes del video.',
            }))
            return

        if not bytes_data or self.ocupado:
            return  # backpressure: mejor saltar un frame que acumular latencia

        self.ocupado = True
        try:
            resultado = await sync_to_async(self._procesar, thread_sensitive=False)(bytes_data)
        except Exception as exc:  # no tumbar el socket por un frame malo
            await self.send(text_data=json.dumps({'tipo': 'error', 'detalle': str(exc)}))
            return
        finally:
            self.ocupado = False

        if resultado:
            await self.send(text_data=json.dumps(resultado))

    def _procesar(self, jpeg_bytes):
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return None

        salida = obtener_detector().detectar(frame)
        resultado_contador = self.contador.actualizar(
            salida['detecciones'], salida['ancho'], salida['alto']
        )

        # Persistencia real: cada cruce nuevo se guarda de inmediato, agregado
        # por minuto. Esto es lo que hace el historial sobrevivir a
        # reconexiones, reinicios del servidor y cambios de cámara.
        if resultado_contador['nuevos']:
            conteo_por_clase = {}
            for item in resultado_contador['nuevos']:
                conteo_por_clase[item['clase']] = conteo_por_clase.get(item['clase'], 0) + 1
            try:
                camara = Camara.objects.get(pk=self.camara_id)
                ConteoVehicular.acumular(camara, conteo_por_clase)
            except Camara.DoesNotExist:
                pass  # la cámara fue borrada; no se pierde el conteo en memoria, solo no se persiste

        salida['contador'] = resultado_contador
        salida['linea'] = {'a': self.contador.a, 'b': self.contador.b}
        salida['camara_id'] = self.camara_id
        salida['tipo'] = 'resultado'
        return salida

    async def _mensaje_control(self, texto):
        try:
            msg = json.loads(texto)
        except json.JSONDecodeError:
            return

        tipo = msg.get('tipo')

        if tipo == 'identificar':
            camara_id = msg.get('camara_id')
            existe = await sync_to_async(Camara.objects.filter(pk=camara_id).exists)()
            if not existe:
                await self.send(text_data=json.dumps({
                    'tipo': 'error',
                    'detalle': f'No existe una cámara con id {camara_id}. Créala en /admin/.',
                }))
                return
            self.camara_id = camara_id
            self.contador = RegistroContadores.obtener(camara_id)
            await self.send(text_data=json.dumps({'tipo': 'identificado', 'camara_id': camara_id}))

        elif tipo == 'linea' and self.camara_id is not None:
            self.contador = RegistroContadores.reiniciar(
                self.camara_id, tuple(msg['a']), tuple(msg['b'])
            )

        elif tipo == 'reiniciar' and self.camara_id is not None:
            # Reinicia solo el conteo en memoria de cruces (para no duplicar
            # al repintar en pantalla); el historial ya persistido en BD
            # no se toca.
            self.contador = RegistroContadores.reiniciar(self.camara_id)

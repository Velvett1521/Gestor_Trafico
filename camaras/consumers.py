import json

from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async

from .deteccion import procesar_frame, reiniciar_conteo
from .models import Camara


class TraficoConsumer(AsyncWebsocketConsumer):
    """
    Protocolo:
      cliente -> servidor (texto JSON): {"tipo": "identificar", "camara_id": N}
      cliente -> servidor (bytes): frame JPEG
      cliente -> servidor (texto JSON): {"tipo": "linea", "y": 0.5}
                                        {"tipo": "reiniciar"}
      servidor -> cliente (texto JSON): {"tipo": "resultado", ...}

    Nota: el volcado del buffer de conteos a BD ya NO se hace aquí (era
    por frame, saturaba el thread pool y bloqueaba el GIL). Ahora lo hace
    un hilo daemon en deteccion.py cada 5 segundos, independientemente
    de cuántos frames estén llegando.
    """

    async def connect(self):
        self.camara_id = None
        self.linea_y_frac = 0.5
        self.ocupado = False
        await self.accept()
        await self.send(text_data=json.dumps({'tipo': 'listo'}))

    async def disconnect(self, close_code):
        self.camara_id = None
        self.ocupado = False

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
            return  # backpressure

        self.ocupado = True
        try:
            resultado = await sync_to_async(procesar_frame, thread_sensitive=False)(
                self.camara_id, bytes_data, self.linea_y_frac
            )
        except Exception as exc:
            await self.send(text_data=json.dumps({'tipo': 'error', 'detalle': str(exc)}))
            return
        finally:
            self.ocupado = False

        if resultado:
            resultado['tipo'] = 'resultado'
            resultado['camara_id'] = self.camara_id
            resultado['linea_y_frac'] = self.linea_y_frac
            await self.send(text_data=json.dumps(resultado))

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
            await self.send(text_data=json.dumps({'tipo': 'identificado', 'camara_id': camara_id}))

        elif tipo == 'linea' and self.camara_id is not None:
            self.linea_y_frac = float(msg.get('y', self.linea_y_frac))
            await self.send(text_data=json.dumps({
                'tipo': 'linea_actualizada',
                'linea_y_frac': self.linea_y_frac,
            }))

        elif tipo == 'reiniciar' and self.camara_id is not None:
            await sync_to_async(reiniciar_conteo, thread_sensitive=False)(self.camara_id)
            await self.send(text_data=json.dumps({'tipo': 'reiniciado'}))
from django.urls import re_path
from .consumers import TraficoConsumer

websocket_urlpatterns = [
    re_path(r'^ws/trafico/$', TraficoConsumer.as_asgi()),
]
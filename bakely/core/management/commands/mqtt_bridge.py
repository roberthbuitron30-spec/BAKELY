"""
Puente MQTT → BAKELY (alternativa a Node-RED).

Tópicos esperados:  upec/bakely/<dispositivo>/<variable>
Payload: número ("24.3") o JSON {"valor": 24.3, "ts": "2026-10-13T10:00:00-05:00", "equipo": "TQ-01"}

    pip install paho-mqtt
    python manage.py mqtt_bridge --host 192.168.1.50 --port 1883

Ejemplo de firmware ESP32 (Arduino / PubSubClient):
    client.publish("upec/bakely/esp32-tq01/temperatura", String(tempC, 2).c_str());
    client.publish("upec/bakely/esp32-tq01/ph", String(ph, 2).c_str());
"""
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils.dateparse import parse_datetime

from core.services import procesar_lectura_iot


class Command(BaseCommand):
    help = "Suscribe al broker MQTT y guarda lecturas IoT de los ESP32."

    def add_arguments(self, parser):
        cfg = settings.BAKELY
        parser.add_argument("--host", default=cfg["MQTT_HOST"])
        parser.add_argument("--port", type=int, default=cfg["MQTT_PORT"])
        parser.add_argument("--topic", default=cfg["MQTT_TOPIC"])
        parser.add_argument("--user", default=None)
        parser.add_argument("--password", default=None)

    def handle(self, *args, **o):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            raise CommandError("Instale paho-mqtt: pip install paho-mqtt")

        def on_connect(client, userdata, flags, rc, *a):
            client.subscribe(o["topic"], qos=1)
            self.stdout.write(self.style.SUCCESS(f"Conectado a {o['host']}:{o['port']} · {o['topic']}"))

        def on_message(client, userdata, msg):
            close_old_connections()
            partes = msg.topic.split("/")
            if len(partes) < 4:
                return
            dispositivo, variable = partes[-2], partes[-1]
            raw = msg.payload.decode("utf-8", "ignore").strip()
            try:
                datos = json.loads(raw) if raw.startswith("{") else {"valor": raw}
                lectura = procesar_lectura_iot(
                    dispositivo=dispositivo, variable=variable, valor=datos["valor"],
                    timestamp=parse_datetime(datos["ts"]) if datos.get("ts") else None,
                    equipo_codigo=datos.get("equipo"),
                )
                marca = self.style.ERROR("ALERTA") if lectura.fuera_de_rango else "ok"
                self.stdout.write(f"{lectura} [{marca}]")
            except (ValidationError, KeyError, ValueError) as e:
                self.stderr.write(f"Descartado {msg.topic}={raw}: {e}")

        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bakely-bridge")
        except AttributeError:  # paho-mqtt < 2.0
            client = mqtt.Client(client_id="bakely-bridge")
        if o["user"]:
            client.username_pw_set(o["user"], o["password"])
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(o["host"], o["port"], keepalive=60)
        client.loop_forever()

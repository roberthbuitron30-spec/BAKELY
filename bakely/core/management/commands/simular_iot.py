"""
Simulador de sensores ESP32 (sin hardware). Genera lecturas cada N segundos para
todos los equipos con dispositivo IoT y límites configurados.

    python manage.py simular_iot --intervalo 5 --ciclos 0     # 0 = infinito
    python manage.py simular_iot --alerta TQ-01:TEMP:28        # fuerza un valor
"""
import random
import time

from django.core.management.base import BaseCommand

from core.models import Equipo
from core.services import procesar_lectura_iot


class Command(BaseCommand):
    help = "Simula lecturas IoT para probar el tablero sin hardware."

    def add_arguments(self, parser):
        parser.add_argument("--intervalo", type=float, default=5)
        parser.add_argument("--ciclos", type=int, default=12)
        parser.add_argument("--alerta", default="", help="EQUIPO:VARIABLE:VALOR")

    def handle(self, *args, **o):
        if o["alerta"]:
            eq, var, val = o["alerta"].split(":")
            l = procesar_lectura_iot(dispositivo="simulador", variable=var, valor=val, equipo_codigo=eq)
            self.stdout.write(f"Forzado: {l} fuera_de_rango={l.fuera_de_rango}")
            return
        equipos = [e for e in Equipo.objects.exclude(limites={}) if e.estado in ("OPERANDO", "ALERTA")]
        ciclo = 0
        while o["ciclos"] == 0 or ciclo < o["ciclos"]:
            for eq in equipos:
                for var, (lo, hi) in eq.limites.items():
                    centro, ancho = (float(lo) + float(hi)) / 2, (float(hi) - float(lo))
                    valor = random.gauss(centro, ancho / 5)
                    if random.random() < 0.03:  # 3 % de excursiones
                        valor = float(hi) + ancho * 0.15
                    procesar_lectura_iot(dispositivo=eq.dispositivo_iot or "simulador", variable=var,
                                         valor=round(valor, 3), equipo_codigo=eq.codigo)
            ciclo += 1
            self.stdout.write(f"Ciclo {ciclo}: {len(equipos)} equipos actualizados")
            time.sleep(o["intervalo"])

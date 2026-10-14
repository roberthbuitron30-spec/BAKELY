"""
Pruebas de BAKELY: matriz RBAC, eBR/PCC-1, Kardex/FEFO, IoT, contrato CEDI y exportaciones.

    python manage.py test core
"""
import json
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core import services
from core.models import (
    Despacho, Equipo, Existencia, LecturaIoT, Lote, MovimientoKardex, OrdenProduccion, Producto,
    RegistroAuditoria, RegistroEtapa, UbicacionWMS,
)

User = get_user_model()
CLAVE = "Bakely2026!"


@override_settings(BAKELY={**settings.BAKELY,
                           "IOT_DEVICE_KEY": "clave-iot-test", "CEDI_API_URL": "", "CEDI_API_TOKEN": "tok-cedi"})
class BakelyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_bakely", "--demo", verbosity=0)

    def cliente(self, username):
        c = Client()
        assert c.login(username=username, password=CLAVE), username
        return c

    # ------------------------------------------------------------------ páginas
    def test_paginas_publicas(self):
        c = Client()
        for url in ["/", "/tienda/", "/tienda/?tab=bebidas", "/tienda/producto/PT-LIC-AGU-01/", "/tienda/carrito/",
                    "/trazabilidad/", "/trazabilidad/?codigo=AGU-2610-00001", "/contadores.json"]:
            r = c.get(url, follow=True)
            self.assertEqual(r.status_code, 200, url)
        lote = Lote.objects.get(codigo="PT-AGU-2610-01")
        r = c.get(f"/trazabilidad/{lote.qr_token}/")
        self.assertContains(r, "Aguardiente")
        self.assertContains(r, "Conforme")

    def test_paginas_planta_operario_y_admin(self):
        orden = OrdenProduccion.objects.get(codigo="OP-B-2610-001")
        d = Despacho.objects.first()
        urls = ["/planta/", "/planta/wms/", "/planta/ordenes/", f"/planta/ordenes/{orden.pk}/",
                "/planta/lotes/PT-AGU-2610-01/", "/planta/despachos/", f"/planta/despachos/{d.pk}/",
                "/planta/reportes/", "/planta/estado.json", "/planta/wms/picking/PT-ALM-PAP-01/?cantidad=100"]
        for u in ("op.fermentacion", "director"):
            c = self.cliente(u)
            for url in urls:
                self.assertEqual(c.get(url).status_code, 200, f"{u} {url}")
        self.assertEqual(self.cliente("director").get("/planta/usuarios/").status_code, 200)

    # ------------------------------------------------------------------ RBAC
    def test_cliente_no_entra_al_terminal(self):
        c = self.cliente("cliente.demo")
        self.assertEqual(c.get("/planta/").status_code, 403)
        self.assertTrue(RegistroAuditoria.objects.filter(accion="DENEGADO", username="cliente.demo").exists())

    def test_operario_no_accede_a_usuarios(self):
        self.assertEqual(self.cliente("op.almacen").get("/planta/usuarios/").status_code, 403)

    def test_dashboard_muestra_candados(self):
        r = self.cliente("op.fermentacion").get("/planta/")
        self.assertContains(r, "Tu estación")
        self.assertContains(r, "Solo lectura")

    def test_operario_solo_registra_su_estacion(self):
        orden = OrdenProduccion.objects.get(codigo="OP-B-2610-001")
        c = self.cliente("op.fermentacion")
        url = reverse("core:registrar_etapa", args=[orden.pk])
        base = {"etapa": "Control de fermentación", "control": "GEN", "variables_texto": "densidad = 1.010"}
        r = c.post(url, {**base, "estacion": "DESTILACION"})
        self.assertEqual(r.status_code, 403)
        r = c.post(url, {**base, "estacion": "FERMENTACION"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(RegistroEtapa.objects.filter(orden=orden, etapa="Control de fermentación").exists())

    def test_pc3_fuera_de_rango_marca_desviacion(self):
        orden = OrdenProduccion.objects.get(codigo="OP-B-2610-002")
        c = self.cliente("op.fermentacion")
        c.post(reverse("core:registrar_etapa", args=[orden.pk]), {
            "estacion": "FERMENTACION", "etapa": "Inoculación", "control": "PC-3",
            "variables_texto": "brix_inicial = 16\nph = 4.6\ntemp_c = 24"})
        reg = RegistroEtapa.objects.filter(orden=orden, control="PC-3").latest("fecha")
        self.assertFalse(reg.conforme)
        self.assertIn("ph", " ".join(reg.desviaciones))

    def test_pcc1_metanol_alto_no_conforme(self):
        orden = OrdenProduccion.objects.get(codigo="OP-B-2610-001")
        alb = Equipo.objects.get(codigo="ALB-01")
        c = self.cliente("op.destilacion")
        c.post(reverse("core:registrar_etapa", args=[orden.pk]), {
            "estacion": "DESTILACION", "etapa": "Segunda destilación", "control": "PCC-1", "equipo": alb.pk,
            "alambique": alb.pk, "volumen_carga_l": "200", "abv_carga": "9", "cabezas_l": "1.5", "abv_cabezas": "75",
            "corazon_l": "20", "abv_corazon": "66", "colas_l": "8", "abv_colas": "22",
            "temp_vapor_corte_cabeza_c": "80", "temp_vapor_corte_cola_c": "94", "metanol_mg_100ml_aa": "160"})
        reg = RegistroEtapa.objects.get(etapa="Segunda destilación")
        self.assertFalse(reg.corte.conforme)
        reg.refresh_from_db()
        self.assertFalse(reg.conforme)

    def test_solo_admin_libera_lotes(self):
        lote = Lote.objects.get(codigo="MP-TUB-2610-01")
        Lote.objects.filter(pk=lote.pk).update(estado="CUARENTENA")
        r = self.cliente("op.almacen").post(reverse("core:lote_liberar", args=[lote.codigo]), {"accion": "liberar"})
        self.assertEqual(r.status_code, 403)
        self.cliente("director").post(reverse("core:lote_liberar", args=[lote.codigo]), {"accion": "liberar"})
        self.assertEqual(Lote.objects.get(pk=lote.pk).estado, "LIBERADO")

    def test_sobrescritura_admin_queda_marcada(self):
        reg = RegistroEtapa.objects.filter(registrado_por__username="op.almidones").first()
        admin = User.objects.get(username="director")
        services.guardar_con_auditoria(admin, reg, {"observaciones": "Corregido por dirección"})
        self.assertTrue(RegistroAuditoria.objects.filter(sobrescritura_admin=True, objeto_id=str(reg.pk)).exists())

    def test_operario_no_edita_otra_estacion_via_servicio(self):
        reg = RegistroEtapa.objects.filter(estacion="ALMIDONES").first()
        with self.assertRaises(Exception):
            services.guardar_con_auditoria(User.objects.get(username="op.envasado"), reg, {"observaciones": "x"})

    # ------------------------------------------------------------------ WMS
    def test_kardex_no_permite_saldo_negativo(self):
        lote = Lote.objects.get(codigo="PT-ALM-PAP-2610-01")
        ub = Existencia.objects.get(lote=lote).ubicacion
        with self.assertRaises(Exception):
            services.registrar_movimiento(user=User.objects.get(username="director"), tipo="SALIDA", lote=lote,
                                          cantidad=99999, ubicacion_origen=ub)

    def test_transferencia_actualiza_existencias(self):
        lote = Lote.objects.get(codigo="PT-ALM-PAP-2610-01")
        origen = Existencia.objects.get(lote=lote).ubicacion
        destino = UbicacionWMS.objects.filter(zona="ZONA-ALM-SECOS").exclude(pk=origen.pk).first()
        c = self.cliente("op.almacen")
        c.post(reverse("core:wms_movimiento"), {"tipo": "TRANSF", "lote": lote.pk, "cantidad": "50",
                                                "ubicacion_origen": origen.pk, "ubicacion_destino": destino.pk})
        self.assertEqual(Existencia.objects.get(lote=lote, ubicacion=destino).cantidad, Decimal("50"))
        self.assertEqual(lote.stock_actual, Decimal("250"))

    def test_picking_fefo(self):
        plan, faltante = services.sugerir_picking(Producto.objects.get(codigo="PT-ALM-PAP-01"), 100)
        self.assertEqual(faltante, 0)
        self.assertEqual(plan[0]["lote"].codigo, "PT-ALM-PAP-2610-01")

    def test_balance_alcohol(self):
        b = OrdenProduccion.objects.get(codigo="OP-B-2610-001").balance_materia()
        self.assertEqual(b["lap_carga"], Decimal("19.000"))
        self.assertGreater(b["recuperacion_corazon_pct"], 70)

    # ------------------------------------------------------------------ IoT
    def test_iot_requiere_clave_y_detecta_alerta(self):
        c = Client()
        payload = [{"dispositivo": "esp32-tq01", "variable": "temperatura", "valor": 24.2},
                   {"dispositivo": "esp32-tq01", "variable": "ph", "valor": 4.9}]
        r = c.post("/api/iot/lecturas/", payload, content_type="application/json")
        self.assertEqual(r.status_code, 403)
        r = c.post("/api/iot/lecturas/", payload, content_type="application/json", HTTP_X_DEVICE_KEY="clave-iot-test")
        self.assertEqual(r.status_code, 201, r.content)
        datos = r.json()["guardadas"]
        self.assertEqual([d["alerta"] for d in datos], [False, True])
        self.assertEqual(Equipo.objects.get(codigo="TQ-01").estado, "ALERTA")

    # ------------------------------------------------------------------ CEDI
    def test_contrato_y_confirmacion_cedi(self):
        d = Despacho.objects.get(codigo="DSP-2610-0001")
        c = self.cliente("op.almacen")
        contrato = c.get(f"/api/cedi/despachos/{d.pk}/contrato/").json()
        self.assertEqual(contrato["tipo_mensaje"], "despacho_planta_hacia_cedi")
        self.assertEqual(contrato["totales"]["botellas"], 24)
        item_lic = next(i for i in contrato["items"] if i["linea"] == "BEBIDA")
        self.assertEqual(item_lic["calidad"]["graduacion_alcoholica_abv"], 40.1)
        self.assertEqual(len(item_lic["calidad"]["seriales"]), 24)
        # sin picking no se puede confirmar
        r = c.post(f"/api/cedi/despachos/{d.pk}/confirmar/", {}, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        d.detalles.update(pickeado=True)
        r = c.post(f"/api/cedi/despachos/{d.pk}/confirmar/", {}, content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Despacho.objects.get(pk=d.pk).estado, "ENVIADO")
        self.assertEqual(MovimientoKardex.objects.filter(despacho=d, tipo="SALIDA").count(), 2)
        # webhook del CEDI
        r = Client().post("/api/cedi/confirmacion/", {"codigo_despacho": d.codigo, "recibido_en": "2026-10-14T09:00:00-05:00"},
                          content_type="application/json", HTTP_AUTHORIZATION="Bearer tok-cedi")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Despacho.objects.get(pk=d.pk).estado, "CONFIRMADO")

    def test_api_operario_no_crea_en_otra_estacion(self):
        c = self.cliente("op.fermentacion")
        r = c.post("/api/planta/despachos/".replace("planta", "cedi"), {
            "codigo": "X", "cedi_destino": "C", "fecha_programada": "2026-10-20T08:00:00-05:00"},
            content_type="application/json")
        self.assertEqual(r.status_code, 403)

    # ------------------------------------------------------------------ exportaciones
    def test_exportaciones(self):
        c = self.cliente("director")
        d = Despacho.objects.first()
        casos = [("/planta/reportes/ebr/PT-AGU-2610-01.pdf", b"%PDF"),
                 ("/planta/reportes/ebr/PT-ALM-PAP-2610-01.pdf", b"%PDF"),
                 ("/planta/reportes/auditoria.xlsx", b"PK"), ("/planta/reportes/auditoria.csv", "﻿".encode()),
                 ("/planta/reportes/kardex.xlsx", b"PK"), ("/planta/reportes/kardex.pdf", b"%PDF"),
                 (f"/planta/reportes/manifiesto/{d.pk}.pdf", b"%PDF"), (f"/planta/reportes/manifiesto/{d.pk}.json", b"{")]
        for url, firma in casos:
            r = c.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertTrue(r.content.startswith(firma), url)
        self.assertEqual(self.cliente("op.almacen").get("/planta/reportes/auditoria.xlsx").status_code, 403)

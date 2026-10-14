"""
BAKELY · Módulo 5 — Vistas de exportación (PDF, Excel, CSV, JSON)

Reúnen los datos desde el ORM y delegan el dibujo a reportes_render.py.
Cada descarga queda registrada en la bitácora (acción EXPORTAR).
"""
import json
from datetime import datetime, time

from django.conf import settings
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import reportes_render as R
from . import services
from .models import (
    ConteoCiclico, CorteDestilacion, Despacho, Existencia, LecturaIoT, Lote, MovimientoKardex,
    OrdenProduccion, RegistroAuditoria,
)
from .permissions import admin_requerido, personal_planta_requerido

TIPOS = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json; charset=utf-8",
}


def _descarga(contenido, nombre, ext):
    resp = HttpResponse(contenido, content_type=TIPOS[ext])
    resp["Content-Disposition"] = f'attachment; filename="{nombre}.{ext}"'
    return resp


def _meta(request, url_traz=None):
    cfg = settings.BAKELY
    return {"institucion": cfg["INSTITUCION"], "planta": cfg["PLANTA_NOMBRE"],
            "url_trazabilidad": request.build_absolute_uri(url_traz) if url_traz else ""}


def _rango(request):
    hoy = timezone.localdate()
    desde = request.GET.get("desde") or hoy.replace(day=1).isoformat()
    hasta = request.GET.get("hasta") or hoy.isoformat()
    tz = timezone.get_current_timezone()
    d = timezone.make_aware(datetime.combine(datetime.fromisoformat(desde).date(), time.min), tz)
    h = timezone.make_aware(datetime.combine(datetime.fromisoformat(hasta).date(), time.max), tz)
    return d, h, f"{desde} a {hasta}"


def _fmt(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M") if dt else None


# =============================================================================
# 1. Informe oficial de lote (eBR) — PDF
# =============================================================================
def datos_ebr(request, lote: Lote):
    orden = lote.orden
    registros = lote.registros.all() if not orden else orden.registros.all()
    registros = registros.select_related("registrado_por", "aprobado_por").order_by("fecha")
    cortes = CorteDestilacion.objects.filter(registro__in=registros).select_related("alambique")
    iot = []
    if orden:
        iot = (LecturaIoT.objects.filter(orden=orden).values("equipo__codigo", "variable")
               .annotate(mn=Min("valor"), mx=Max("valor"), pr=Avg("valor"), n=Count("id"),
                         al=Count("id", filter=Q(fuera_de_rango=True))))
    ok, _ = lote.puede_liberarse()
    firmas = []
    for r in registros:
        if r.aprobado_por:
            firmas.append({"cargo": f"Aprobó {r.get_estacion_display()}",
                           "nombre": r.aprobado_por.get_full_name() or r.aprobado_por.username,
                           "fecha": _fmt(r.fecha_aprobacion)})
    firmas = firmas[-2:] + [{"cargo": "Director de Planta UPEC",
                             "nombre": lote.liberado_por.get_full_name() if lote.liberado_por else None,
                             "fecha": _fmt(lote.fecha_liberacion)}]
    return {
        "meta": _meta(request, f"/trazabilidad/{lote.qr_token}/"),
        "conforme_global": ok and all(r.conforme for r in registros) if registros else None,
        "lote": {
            "codigo": lote.codigo, "producto": lote.producto.nombre, "sku": lote.producto.codigo,
            "linea": lote.producto.get_linea_display(), "estado": lote.get_estado_display(),
            "cantidad": lote.cantidad_inicial, "unidad": lote.unidad,
            "elaboracion": lote.fecha_elaboracion.isoformat(),
            "caducidad": lote.fecha_caducidad.isoformat() if lote.fecha_caducidad else None,
            "abv": lote.abv_final, "humedad": lote.humedad_final_pct, "cenizas": lote.cenizas_pct,
            "pcc1_conforme": lote.pcc1_conforme, "certificado": lote.certificado_inocuidad,
            "liberado_por": (lote.liberado_por.get_full_name() or lote.liberado_por.username) if lote.liberado_por else None,
            "fecha_liberacion": _fmt(lote.fecha_liberacion),
        },
        "orden": {"codigo": orden.codigo, "equipo": orden.equipo.codigo if orden and orden.equipo else None} if orden else {},
        "origenes": [{"lote": o.codigo, "producto": o.producto.nombre, "proveedor": o.proveedor,
                      "procedencia": o.origen_geografico, "cantidad": f"{o.cantidad_inicial} {o.unidad}"}
                     for o in lote.lotes_origen.select_related("producto")],
        "registros": [{"fecha": _fmt(r.fecha), "estacion": r.get_estacion_display(), "etapa": r.etapa,
                       "control": r.control, "variables": r.variables, "conforme": r.conforme,
                       "desviaciones": r.desviaciones,
                       "registrado_por": r.registrado_por.get_full_name() or r.registrado_por.username,
                       "aprobado_por": (r.aprobado_por.username if r.aprobado_por else "")} for r in registros],
        "cortes": [{"alambique": c.alambique.codigo, "carga_l": c.volumen_carga_l, "abv_carga": c.abv_carga,
                    "cabezas_l": c.cabezas_l, "corazon_l": c.corazon_l, "abv_corazon": c.abv_corazon,
                    "colas_l": c.colas_l, "metanol": c.metanol_mg_100ml_aa, "conforme": c.conforme,
                    "motivos": c.motivos_no_conformidad} for c in cortes],
        "iot_resumen": [{"equipo": i["equipo__codigo"], "variable": i["variable"], "min": round(i["mn"], 2),
                         "max": round(i["mx"], 2), "promedio": round(i["pr"], 2), "n": i["n"], "alertas": i["al"]}
                        for i in iot],
        "balance": orden.balance_materia() if orden else {},
        "firmas": firmas,
    }


@personal_planta_requerido
def exportar_ebr_pdf(request, codigo):
    lote = get_object_or_404(Lote.objects.select_related("producto", "orden__equipo", "liberado_por"), codigo=codigo)
    pdf = R.pdf_ebr(datos_ebr(request, lote))
    services.auditar(request.user, "EXPORTAR", lote, detalle="Informe eBR PDF")
    return _descarga(pdf, f"eBR_{lote.codigo}", "pdf")


# =============================================================================
# 2. Bitácora de auditoría — Excel / CSV (solo administrador)
# =============================================================================
@admin_requerido
def exportar_auditoria(request, ext):
    if ext not in ("xlsx", "csv"):
        raise Http404
    d, h, periodo = _rango(request)
    qs = RegistroAuditoria.objects.filter(timestamp__range=(d, h))
    if request.GET.get("usuario"):
        qs = qs.filter(username=request.GET["usuario"])
    if request.GET.get("solo_sobrescrituras"):
        qs = qs.filter(sobrescritura_admin=True)
    filas = [{**r, "timestamp": _fmt(r["timestamp"])} for r in qs.values(
        "timestamp", "username", "rol", "estacion_usuario", "accion", "modelo", "objeto_id", "objeto_repr",
        "estacion_objeto", "cambios", "sobrescritura_admin", "ip", "detalle")]
    services.auditar(request.user, "EXPORTAR", detalle=f"Bitácora {ext} {periodo} ({len(filas)} filas)")
    contenido = R.xlsx_auditoria(filas) if ext == "xlsx" else R.csv_auditoria(filas)
    return _descarga(contenido, f"bitacora_auditoria_{d:%Y%m%d}_{h:%Y%m%d}", ext)


# =============================================================================
# 3. Kardex y rendimiento WMS — Excel / PDF
# =============================================================================
def datos_kardex(request):
    d, h, periodo = _rango(request)
    movs = (MovimientoKardex.objects.filter(fecha__range=(d, h))
            .select_related("lote__producto", "ubicacion_origen", "ubicacion_destino", "usuario").order_by("fecha"))
    if request.GET.get("sku"):
        movs = movs.filter(lote__producto__codigo=request.GET["sku"])
    signo = lambda m: {1: "+", -1: "-", 0: "="}[m.signo]
    ordenes = OrdenProduccion.objects.filter(
        Q(fecha_inicio__range=(d, h)) | Q(fecha_cierre__range=(d, h))).select_related("producto")
    rend = []
    for o in ordenes:
        b = o.balance_materia()
        rend.append({"orden": o.codigo, "producto": o.producto.nombre, "linea": o.linea, **b})
    mermas = (movs.filter(tipo="MERMA").values("motivo_merma", "unidad").annotate(c=Sum("cantidad")))
    hoy = timezone.localdate()
    return {
        "meta": _meta(request), "periodo": periodo,
        "movimientos": [{"fecha": _fmt(m.fecha), "tipo": m.get_tipo_display(), "sku": m.lote.producto.codigo,
                         "producto": m.lote.producto.nombre, "lote": m.lote.codigo, "cantidad": m.cantidad,
                         "signo": signo(m), "unidad": m.unidad,
                         "origen": m.ubicacion_origen.codigo if m.ubicacion_origen else None,
                         "destino": m.ubicacion_destino.codigo if m.ubicacion_destino else None,
                         "saldo": m.saldo_lote, "motivo_merma": m.get_motivo_merma_display() if m.motivo_merma else "",
                         "usuario": m.usuario.username, "estacion": m.estacion, "referencia": m.referencia}
                        for m in movs],
        "rendimiento": rend,
        "mermas": [{"motivo": dict(MovimientoKardex.MotivoMerma.choices).get(x["motivo_merma"], x["motivo_merma"]),
                    "cantidad": x["c"], "unidad": x["unidad"]} for x in mermas],
        "existencias": [{"zona": e.ubicacion.zona, "ubicacion": e.ubicacion.codigo, "sku": e.lote.producto.codigo,
                         "lote": e.lote.codigo, "cantidad": e.cantidad, "unidad": e.lote.unidad,
                         "caducidad": e.lote.fecha_caducidad.isoformat() if e.lote.fecha_caducidad else None,
                         "dias": (e.lote.fecha_caducidad - hoy).days if e.lote.fecha_caducidad else None,
                         "estado": e.lote.estado}
                        for e in Existencia.objects.filter(cantidad__gt=0).select_related("lote__producto", "ubicacion")],
        "conteos": [{"fecha": _fmt(c.fecha), "ubicacion": c.ubicacion.codigo, "lote": c.lote.codigo,
                     "sistema": c.cantidad_sistema, "fisico": c.cantidad_fisica}
                    for c in ConteoCiclico.objects.filter(fecha__range=(d, h)).select_related("ubicacion", "lote")],
        "ira": ConteoCiclico.ira(desde=d),
    }


@personal_planta_requerido
def exportar_kardex(request, ext):
    if ext not in ("xlsx", "pdf"):
        raise Http404
    datos = datos_kardex(request)
    contenido = R.xlsx_kardex(datos) if ext == "xlsx" else R.pdf_kardex(datos)
    services.auditar(request.user, "EXPORTAR", detalle=f"Kardex {ext} {datos['periodo']}")
    return _descarga(contenido, f"kardex_wms_{timezone.localdate():%Y%m%d}", ext)


# =============================================================================
# 4. Manifiesto de carga al CEDI — PDF / JSON
# =============================================================================
@personal_planta_requerido
def exportar_manifiesto(request, pk, ext):
    if ext not in ("pdf", "json"):
        raise Http404
    d = get_object_or_404(Despacho, pk=pk)
    contrato = d.payload_enviado or services.construir_contrato_cedi(d)
    services.auditar(request.user, "EXPORTAR", d, detalle=f"Manifiesto {ext}")
    if ext == "json":
        return _descarga(json.dumps(contrato, ensure_ascii=False, indent=2, default=str), f"cedi_{d.codigo}", "json")
    return _descarga(R.pdf_manifiesto(contrato, _meta(request)), f"manifiesto_{d.codigo}", "pdf")

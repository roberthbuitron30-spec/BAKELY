"""
BAKELY · Lógica de negocio (capa de servicios)

Toda escritura de inventario, liberación de lotes, despacho e IoT pasa por aquí,
para que vistas HTML, API y comandos compartan las mismas reglas y la misma auditoría.
"""
import json
import logging
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.forms.models import model_to_dict
from django.utils import timezone

from .middleware import ip_actual
from .models import (
    Despacho, Equipo, Existencia, LecturaIoT, Lote, MovimientoKardex, Producto,
    RegistroAuditoria, UnidadSerializada,
)
from .permissions import es_admin, estacion_de, puede_editar_estacion, rol_de

log = logging.getLogger("bakely")


# =============================================================================
# AUDITORÍA
# =============================================================================
def _jsonable(v):
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "pk"):
        return v.pk
    return v


def diff_campos(antes: dict, despues: dict):
    cambios = {}
    for k in set(antes) | set(despues):
        a, d = _jsonable(antes.get(k)), _jsonable(despues.get(k))
        if a != d:
            cambios[k] = [a, d]
    return cambios


def snapshot(instancia):
    return {k: _jsonable(v) for k, v in model_to_dict(instancia).items() if not hasattr(v, "read")}


def auditar(user, accion, obj=None, cambios=None, detalle="", estacion_objeto=""):
    """Inserta una fila en la bitácora (solo inserción). Detecta sobrescritura administrativa."""
    autenticado = bool(user and user.is_authenticated)
    est_obj = estacion_objeto or (getattr(obj, "estacion_responsable", "") if obj is not None else "")
    autor_original = None
    if obj is not None:
        for campo in ("registrado_por_id", "creado_por_id", "envasado_por_id", "usuario_id"):
            if getattr(obj, campo, None):
                autor_original = getattr(obj, campo)
                break
    sobrescritura = bool(
        autenticado and es_admin(user) and accion == "EDITAR"
        and autor_original and autor_original != user.pk
    )
    return RegistroAuditoria.objects.create(
        usuario=user if autenticado else None,
        username=user.get_username() if autenticado else "anónimo",
        rol=rol_de(user) or "" if autenticado else "",
        estacion_usuario=estacion_de(user) or "" if autenticado else "",
        accion=accion,
        modelo=obj.__class__.__name__ if obj is not None else "",
        objeto_id=str(getattr(obj, "pk", "") or ""),
        objeto_repr=str(obj)[:200] if obj is not None else "",
        estacion_objeto=est_obj or "",
        cambios=cambios or {},
        sobrescritura_admin=sobrescritura,
        ip=ip_actual(),
        detalle=detalle[:255],
    )


def guardar_con_auditoria(user, instancia, campos_nuevos: dict):
    """Aplica cambios a una instancia verificando permisos por estación y registrando el diff."""
    if not puede_editar_estacion(user, getattr(instancia, "estacion_responsable", None)):
        auditar(user, "DENEGADO", instancia, detalle="Edición fuera de la estación asignada")
        raise PermissionDenied("Solo lectura: esta estación no está asignada a su usuario.")
    antes = snapshot(instancia)
    for k, v in campos_nuevos.items():
        setattr(instancia, k, v)
    instancia.full_clean()
    instancia.save()
    cambios = diff_campos(antes, snapshot(instancia))
    if cambios:
        auditar(user, "EDITAR", instancia, cambios=cambios)
    return instancia


# =============================================================================
# KARDEX E INVENTARIO
# =============================================================================
@transaction.atomic
def registrar_movimiento(*, user, tipo, lote, cantidad, ubicacion_origen=None, ubicacion_destino=None,
                         orden=None, despacho=None, motivo_merma="", referencia="", estacion=None):
    """
    Único punto de escritura de existencias. Bloquea filas (SELECT … FOR UPDATE)
    para evitar saldos negativos con operarios concurrentes.
    """
    cantidad = Decimal(str(cantidad))
    if cantidad <= 0:
        raise ValidationError("La cantidad debe ser positiva.")
    estacion = estacion or estacion_de(user) or (ubicacion_destino or ubicacion_origen).estacion_responsable
    if not puede_editar_estacion(user, estacion):
        auditar(user, "DENEGADO", lote, detalle=f"Movimiento {tipo} bloqueado", estacion_objeto=estacion)
        raise PermissionDenied("No puede registrar movimientos de otra estación.")

    T = MovimientoKardex.Tipo
    if tipo in (T.ENTRADA, T.PRODUCCION) and not ubicacion_destino:
        raise ValidationError("Las entradas requieren ubicación destino.")
    if tipo in (T.CONSUMO, T.SALIDA, T.MERMA) and not ubicacion_origen:
        raise ValidationError("Las salidas requieren ubicación origen.")
    if tipo == T.TRANSFERENCIA and not (ubicacion_origen and ubicacion_destino):
        raise ValidationError("La transferencia requiere origen y destino.")
    if tipo == T.MERMA and not motivo_merma:
        raise ValidationError("Indique el motivo de la merma.")

    if ubicacion_origen:
        ex_o, _ = Existencia.objects.select_for_update().get_or_create(lote=lote, ubicacion=ubicacion_origen)
        if ex_o.cantidad < cantidad:
            raise ValidationError(
                f"Stock insuficiente en {ubicacion_origen}: disponible {ex_o.cantidad} {lote.unidad}."
            )
        ex_o.cantidad = F("cantidad") - cantidad
        ex_o.save(update_fields=["cantidad", "actualizado"])
    if ubicacion_destino:
        if lote.estado == Lote.Estado.RECHAZADO and ubicacion_destino.zona != "ZONA-MER":
            raise ValidationError("Un lote rechazado solo puede moverse a ZONA-MER.")
        ex_d, _ = Existencia.objects.select_for_update().get_or_create(lote=lote, ubicacion=ubicacion_destino)
        ex_d.cantidad = F("cantidad") + cantidad
        ex_d.save(update_fields=["cantidad", "actualizado"])

    saldo = Existencia.objects.filter(lote=lote).aggregate(s=Sum("cantidad"))["s"] or Decimal("0")
    mov = MovimientoKardex.objects.create(
        tipo=tipo, lote=lote, cantidad=cantidad, unidad=lote.unidad, orden=orden, despacho=despacho,
        ubicacion_origen=ubicacion_origen, ubicacion_destino=ubicacion_destino,
        motivo_merma=motivo_merma, saldo_lote=saldo, referencia=referencia, usuario=user, estacion=estacion,
    )
    if saldo == 0 and tipo in (T.SALIDA, T.CONSUMO) and lote.estado == Lote.Estado.LIBERADO:
        Lote.objects.filter(pk=lote.pk).update(estado=Lote.Estado.AGOTADO)
    auditar(user, "CREAR", mov, detalle=f"Kardex {tipo} {cantidad} {lote.unidad}")
    return mov


def sugerir_picking(producto: Producto, cantidad):
    """
    Propone lotes/ubicaciones para cubrir `cantidad` según la regla del producto:
      FEFO → ordena por fecha de caducidad (bebidas y almidones envasados)
      FIFO → ordena por fecha de elaboración (materias primas)
    Solo considera lotes LIBERADOS.
    """
    orden = ("lote__fecha_caducidad", "lote__fecha_elaboracion") if producto.regla_rotacion == "FEFO" \
        else ("lote__fecha_elaboracion", "lote__id")
    qs = (Existencia.objects
          .filter(lote__producto=producto, lote__estado=Lote.Estado.LIBERADO, cantidad__gt=0)
          .select_related("lote", "ubicacion").order_by(*orden))
    restante = Decimal(str(cantidad))
    plan = []
    for ex in qs:
        if restante <= 0:
            break
        tomar = min(ex.cantidad, restante)
        plan.append({"lote": ex.lote, "ubicacion": ex.ubicacion, "cantidad": tomar,
                     "caduca": ex.lote.fecha_caducidad})
        restante -= tomar
    return plan, max(restante, Decimal("0"))


# =============================================================================
# LIBERACIÓN DE LOTES (solo administrador)
# =============================================================================
@transaction.atomic
def liberar_lote(user, lote: Lote, forzar=False, motivo=""):
    if not es_admin(user):
        auditar(user, "DENEGADO", lote, detalle="Intento de liberación sin rol admin")
        raise PermissionDenied("Solo el Director de Planta puede liberar lotes.")
    ok, motivos = lote.puede_liberarse()
    if not ok and not forzar:
        raise ValidationError(motivos)
    antes = lote.estado
    lote.estado = Lote.Estado.LIBERADO
    lote.liberado_por = user
    lote.fecha_liberacion = timezone.now()
    lote.save(update_fields=["estado", "liberado_por", "fecha_liberacion"])
    auditar(user, "LIBERAR", lote, cambios={"estado": [antes, lote.estado]},
            detalle=("LIBERACIÓN FORZADA: " + motivo + " | " + "; ".join(motivos)) if not ok else "Conforme")
    return lote


@transaction.atomic
def retener_lote(user, lote: Lote, motivo, rechazar=False):
    if not es_admin(user):
        raise PermissionDenied("Solo el Director de Planta puede retener o rechazar lotes.")
    antes = lote.estado
    lote.estado = Lote.Estado.RECHAZADO if rechazar else Lote.Estado.RETENIDO
    lote.save(update_fields=["estado"])
    lote.unidades.update(estado=UnidadSerializada.Estado.BLOQUEADA)
    auditar(user, "RECHAZAR", lote, cambios={"estado": [antes, lote.estado]}, detalle=motivo)
    return lote


# =============================================================================
# CONTRATO JSON PLANTA → CEDI
# =============================================================================
CONTRATO_VERSION = "1.2.0"


def construir_contrato_cedi(despacho: Despacho) -> dict:
    """
    Contrato estándar `despacho_planta_hacia_cedi`.
    Estructura estable y versionada: el CEDI valida `version_contrato` antes de procesar.
    """
    cfg = settings.BAKELY
    items = []
    for d in despacho.detalles.select_related("lote__producto", "ubicacion_origen"):
        lote, prod = d.lote, d.lote.producto
        calidad = {"estado_lote": lote.estado, "certificado_inocuidad": lote.certificado_inocuidad or None}
        if prod.linea == "BEBIDA":
            calidad.update({
                "graduacion_alcoholica_abv": float(lote.abv_final or prod.graduacion_abv or 0),
                "pcc1_conforme": lote.pcc1_conforme,
                "seriales": list(lote.unidades.filter(estado__in=["BODEGA", "DESPACHO"])
                                 .values_list("serial", flat=True)[: d.unidades_empaque or 0]),
            })
        else:
            calidad.update({
                "humedad_pct": float(lote.humedad_final_pct) if lote.humedad_final_pct is not None else None,
                "cenizas_pct": float(lote.cenizas_pct) if lote.cenizas_pct is not None else None,
            })
        items.append({
            "sku": prod.codigo,
            "descripcion": prod.nombre,
            "linea": prod.linea,
            "lote": lote.codigo,
            "cantidad": float(d.cantidad),
            "unidad": lote.unidad,
            "unidades_empaque": d.unidades_empaque,
            "contenido_neto_por_unidad": float(prod.contenido_neto) if prod.contenido_neto else None,
            "codigo_palet": d.codigo_palet or None,
            "fecha_elaboracion": lote.fecha_elaboracion.isoformat(),
            "fecha_caducidad": lote.fecha_caducidad.isoformat() if lote.fecha_caducidad else None,
            "regla_rotacion": prod.regla_rotacion,
            "ubicacion_origen": d.ubicacion_origen.codigo,
            "calidad": calidad,
            "trazabilidad_url": f"/trazabilidad/{lote.qr_token}/",
        })
    return {
        "tipo_mensaje": "despacho_planta_hacia_cedi",
        "version_contrato": CONTRATO_VERSION,
        "emitido_en": timezone.now().isoformat(),
        "origen": {
            "planta_codigo": cfg["PLANTA_CODIGO"],
            "planta_nombre": cfg["PLANTA_NOMBRE"],
            "institucion": cfg["INSTITUCION"],
        },
        "destino": {"cedi_codigo": despacho.cedi_destino},
        "despacho": {
            "codigo": despacho.codigo,
            "fecha_programada": despacho.fecha_programada.isoformat(),
            "guia_remision": despacho.guia_remision or None,
            "transporte": {
                "transportista": despacho.transportista,
                "placa": despacho.placa_vehiculo,
                "conductor": despacho.conductor,
                "condicion_temperatura": despacho.temperatura_transporte,
            },
        },
        "totales": {
            "lineas": len(items),
            "kg_almidon": sum(i["cantidad"] for i in items if i["linea"] == "ALMIDON" and i["unidad"] == "kg"),
            "botellas": sum(i["unidades_empaque"] for i in items if i["linea"] == "BEBIDA"),
        },
        "items": items,
    }


@transaction.atomic
def confirmar_despacho(user, despacho: Despacho, enviar_api=True):
    """Descarga inventario (Kardex SALIDA), congela el contrato y lo envía al CEDI si hay URL configurada."""
    if not puede_editar_estacion(user, despacho.estacion_responsable):
        raise PermissionDenied("Solo Almacén/Despacho o el administrador pueden confirmar despachos.")
    if despacho.estado not in (Despacho.Estado.PREPARACION, Despacho.Estado.LISTO, Despacho.Estado.ERROR):
        raise ValidationError("El despacho ya fue enviado.")
    pendientes = despacho.detalles.filter(pickeado=False).count()
    if pendientes:
        raise ValidationError(f"Faltan {pendientes} líneas por pickear.")
    for d in despacho.detalles.select_related("lote", "ubicacion_origen"):
        if d.lote.estado != Lote.Estado.LIBERADO:
            raise ValidationError(f"El lote {d.lote} no está liberado.")
        registrar_movimiento(user=user, tipo=MovimientoKardex.Tipo.SALIDA, lote=d.lote, cantidad=d.cantidad,
                             ubicacion_origen=d.ubicacion_origen, despacho=despacho,
                             referencia=despacho.codigo, estacion="ALMACEN")
        seriales = d.lote.unidades.filter(estado="BODEGA")[: d.unidades_empaque]
        UnidadSerializada.objects.filter(pk__in=[u.pk for u in seriales]).update(estado="DESPACHO")

    payload = construir_contrato_cedi(despacho)
    despacho.payload_enviado = payload
    despacho.fecha_envio = timezone.now()
    despacho.estado = Despacho.Estado.ENVIADO
    if enviar_api and settings.BAKELY.get("CEDI_API_URL"):
        try:
            despacho.respuesta_cedi = enviar_json(
                settings.BAKELY["CEDI_API_URL"], payload, settings.BAKELY.get("CEDI_API_TOKEN")
            )
        except Exception as exc:  # el despacho físico ya salió: se marca para reintento
            log.exception("Error enviando contrato al CEDI")
            despacho.estado = Despacho.Estado.ERROR
            despacho.respuesta_cedi = {"error": str(exc)}
    despacho.save()
    auditar(user, "API", despacho, detalle=f"Contrato CEDI v{CONTRATO_VERSION} → {despacho.estado}")
    return despacho


def enviar_json(url, payload, token=None, timeout=15):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8") or "{}"
        return {"status": resp.status, "body": json.loads(body) if body.strip().startswith("{") else body}


# =============================================================================
# IoT
# =============================================================================
VARIABLE_ALIAS = {
    "temperatura": "TEMP", "temp": "TEMP", "ph": "PH", "brix": "BRIX", "densidad": "DENS",
    "abv": "ABV", "temp_vapor": "TVAP", "vapor": "TVAP", "humedad": "HUM", "nivel": "NIVEL",
    "presion": "PRES",
}


def procesar_lectura_iot(*, dispositivo, variable, valor, timestamp=None, equipo_codigo=None):
    """
    Guarda una lectura, marca fuera de rango según los límites del equipo y
    actualiza el estado del equipo (OPERANDO ↔ ALERTA). Devuelve la LecturaIoT.
    """
    variable = VARIABLE_ALIAS.get(str(variable).lower(), str(variable).upper())
    if variable not in LecturaIoT.Variable.values:
        raise ValidationError(f"Variable IoT desconocida: {variable}")
    filtro = {"codigo": equipo_codigo} if equipo_codigo else {"dispositivo_iot": dispositivo}
    equipo = Equipo.objects.filter(**filtro).first()
    if not equipo:
        raise ValidationError(f"No hay equipo asociado al dispositivo {dispositivo or equipo_codigo}.")
    valor = Decimal(str(valor))
    orden_activa = equipo.ordenes.filter(estado="PROC").order_by("-fecha_inicio").first()
    fuera = equipo.fuera_de_rango(variable, valor)
    lectura = LecturaIoT.objects.create(
        equipo=equipo, orden=orden_activa, variable=variable, valor=valor,
        dispositivo=dispositivo or equipo.dispositivo_iot, timestamp=timestamp or timezone.now(),
        fuera_de_rango=fuera,
    )
    nuevo_estado = None
    if fuera and equipo.estado == Equipo.EstadoEquipo.OPERANDO:
        nuevo_estado = Equipo.EstadoEquipo.ALERTA
    elif not fuera and equipo.estado == Equipo.EstadoEquipo.ALERTA:
        # vuelve a OPERANDO solo si ninguna variable sigue fuera de rango
        sigue = any(
            (l := equipo.ultima_lectura(v)) and l.fuera_de_rango
            for v in equipo.limites.keys() if v != variable
        )
        if not sigue:
            nuevo_estado = Equipo.EstadoEquipo.OPERANDO
    if variable == "NIVEL":
        Equipo.objects.filter(pk=equipo.pk).update(nivel_actual=valor)
    if nuevo_estado:
        Equipo.objects.filter(pk=equipo.pk).update(estado=nuevo_estado)
    return lectura

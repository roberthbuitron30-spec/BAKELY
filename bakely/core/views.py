"""
BAKELY · Vistas HTML

Regla aplicada en todas las vistas de planta:
  · GET  → cualquier personal de planta ve todo (Operarios "ven todo").
  · POST → solo si la estación del dato coincide con la del operario, o si es admin.
  · Clientes → tienda, carrito, visor QR. Nunca el terminal de planta.
Los ViewSets de la API REST están en api_views.py.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    CheckoutForm, CorteDestilacionForm, MovimientoForm, RecepcionMPForm, RegistroEtapaForm, UsuarioPlantaForm,
)
from .models import (
    CorteDestilacion, Despacho, DetallePedido, Equipo, Estacion, Existencia, LecturaIoT, Linea, Lote,
    MovimientoKardex, OrdenProduccion, Pedido, Producto, RegistroAuditoria, RegistroEtapa, UbicacionWMS,
    UnidadSerializada, Zona,
)
from .permissions import (
    admin_requerido, es_admin, es_personal_planta, estacion_de, personal_planta_requerido,
    puede_editar_estacion,
)

User = get_user_model()


# =============================================================================
# MÓDULO 0 · LANDING
# =============================================================================
def contadores_publicos():
    litros = CorteDestilacion.objects.filter(conforme=True).aggregate(s=Sum("corazon_l"))["s"] or 0
    kg_almidon = (MovimientoKardex.objects
                  .filter(tipo="PRODUCCION", lote__producto__linea=Linea.ALMIDON, unidad="kg")
                  .aggregate(s=Sum("cantidad"))["s"] or 0)
    lotes_cert = Lote.objects.filter(tipo="PT", estado__in=["LIBERADO", "AGOTADO"]).count()
    return {"litros_destilados": float(litros), "kg_almidon": float(kg_almidon), "lotes_certificados": lotes_cert}


def landing(request):
    return render(request, "core/landing.html", {"contadores": contadores_publicos()})


def contadores_json(request):
    return JsonResponse(contadores_publicos())


# =============================================================================
# MÓDULO 1 · TIENDA Y TRAZABILIDAD (CLIENTE)
# =============================================================================
def catalogo(request):
    base = Producto.objects.filter(publicado_tienda=True, activo=True).select_related("categoria")
    return render(request, "tienda/catalogo.html", {
        "almidones": base.filter(linea=Linea.ALMIDON),
        "bebidas": base.filter(linea=Linea.BEBIDA),
        "tab": request.GET.get("tab", "almidones"),
    })


def producto_detalle(request, codigo):
    p = get_object_or_404(Producto.objects.select_related("categoria"), codigo=codigo, activo=True)
    if not p.publicado_tienda and not es_personal_planta(request.user):
        raise Http404
    return render(request, "tienda/producto.html", {"p": p, "disponible": p.stock_total() > 0})


@require_POST
def carrito_agregar(request, codigo):
    p = get_object_or_404(Producto, codigo=codigo, publicado_tienda=True, activo=True)
    cantidad = max(1, min(int(request.POST.get("cantidad", 1) or 1), 99))
    carrito = request.session.get("carrito", {})
    carrito[p.codigo] = carrito.get(p.codigo, 0) + cantidad
    request.session["carrito"] = carrito
    messages.success(request, f"{p.nombre} agregado al carrito.")
    return redirect(request.POST.get("next") or "core:carrito")


@require_POST
def carrito_quitar(request, codigo):
    carrito = request.session.get("carrito", {})
    carrito.pop(codigo, None)
    request.session["carrito"] = carrito
    return redirect("core:carrito")


def _items_carrito(request):
    carrito = request.session.get("carrito", {})
    productos = {p.codigo: p for p in Producto.objects.filter(codigo__in=carrito.keys(), publicado_tienda=True)}
    items = [{"p": productos[c], "cantidad": n, "subtotal": productos[c].precio_venta * n}
             for c, n in carrito.items() if c in productos]
    return items, sum((i["subtotal"] for i in items), Decimal("0"))


def carrito(request):
    items, total = _items_carrito(request)
    form = CheckoutForm(request.POST or None, initial={
        "nombre": request.user.get_full_name() if request.user.is_authenticated else "",
        "email": request.user.email if request.user.is_authenticated else "",
    })
    requiere_edad = any(i["p"].requiere_mayoria_edad for i in items)
    if request.method == "POST" and items and form.is_valid():
        if requiere_edad and not form.cleaned_data["declara_mayor_edad"]:
            form.add_error("declara_mayor_edad", "La venta de bebidas alcohólicas es solo para mayores de 18 años.")
        else:
            with transaction.atomic():
                pedido = Pedido.objects.create(
                    codigo=f"PED-{timezone.now():%y%m%d}-{uuid.uuid4().hex[:5].upper()}",
                    cliente=request.user if request.user.is_authenticated else None,
                    total=total, **form.cleaned_data,
                )
                for i in items:
                    DetallePedido.objects.create(pedido=pedido, producto=i["p"], cantidad=i["cantidad"],
                                                 precio_unitario=i["p"].precio_venta)
            request.session["carrito"] = {}
            messages.success(request, f"Pedido {pedido.codigo} confirmado. Te contactaremos para la entrega.")
            return redirect("core:catalogo")
    return render(request, "tienda/carrito.html", {"items": items, "total": total, "form": form,
                                                   "requiere_edad": requiere_edad})


def trazabilidad_buscar(request):
    """Acepta: serial de botella/saco, código de lote o token UUID del QR."""
    codigo = (request.GET.get("codigo") or "").strip()
    if not codigo:
        return render(request, "tienda/trazabilidad.html", {})
    unidad = UnidadSerializada.objects.select_related("lote").filter(serial__iexact=codigo).first()
    if unidad:
        return redirect("core:trazabilidad_detalle", token=unidad.qr_token)
    lote = Lote.objects.filter(codigo__iexact=codigo, tipo="PT").first()
    if lote:
        return redirect("core:trazabilidad_detalle", token=lote.qr_token)
    try:
        uuid.UUID(codigo)
        return redirect("core:trazabilidad_detalle", token=codigo)
    except ValueError:
        pass
    return render(request, "tienda/trazabilidad.html", {"codigo": codigo, "no_encontrado": True})


def trazabilidad_detalle(request, token):
    unidad = UnidadSerializada.objects.select_related("lote__producto").filter(qr_token=token).first()
    lote = unidad.lote if unidad else Lote.objects.filter(qr_token=token, tipo="PT").first()
    if not lote:
        raise Http404("Código no registrado en BAKELY.")
    from .serializers import TrazabilidadPublicaSerializer
    datos = TrazabilidadPublicaSerializer(lote).data
    return render(request, "tienda/trazabilidad.html", {"t": datos, "lote": lote, "unidad": unidad})


# =============================================================================
# LOGIN DEL TERMINAL
# =============================================================================
class TerminalLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if not es_personal_planta(user):
            form.add_error(None, "Esta cuenta no tiene acceso al terminal de planta.")
            return self.form_invalid(form)
        return super().form_valid(form)


# =============================================================================
# TABLERO OPERATIVO DE PLANTA (WMS / MES)
# =============================================================================
@personal_planta_requerido
def planta_dashboard(request):
    equipos = Equipo.objects.select_related("ubicacion").all()
    tarjetas, alertas = [], []
    for eq in equipos:
        lect = {v: eq.ultima_lectura(v) for v in (eq.limites.keys() or [])}
        alertas += [l for l in lect.values() if l and l.fuera_de_rango]
        tarjetas.append({"eq": eq, "lecturas": lect, "editable": puede_editar_estacion(request.user, eq.estacion)})
    # Equipos en alerta primero, luego operando
    prioridad = {"ALERTA": 0, "OPERANDO": 1}
    tarjetas.sort(key=lambda t: (prioridad.get(t["eq"].estado, 2), t["eq"].codigo))
    ordenes = (OrdenProduccion.objects.filter(estado__in=["PLAN", "PROC", "PAUSA"])
               .select_related("producto", "equipo")[:12])
    stock_zonas = (Existencia.objects.filter(cantidad__gt=0)
                   .values("ubicacion__zona").annotate(lotes=Count("lote", distinct=True), total=Sum("cantidad"))
                   .order_by("ubicacion__zona"))
    proximos_caducar = (Lote.objects.filter(tipo="PT", estado="LIBERADO", fecha_caducidad__isnull=False)
                        .order_by("fecha_caducidad")[:5])
    return render(request, "planta/dashboard.html", {
        "tarjetas": tarjetas,
        "ordenes": ordenes,
        "alertas": alertas,
        "stock_zonas": stock_zonas,
        "zonas": dict(Zona.choices),
        "proximos_caducar": proximos_caducar,
        "estaciones": Estacion.choices,
        "lotes_cuarentena": Lote.objects.filter(estado="CUARENTENA").count(),
        "ira": services_ira(),
        "contadores": contadores_publicos(),
    })


def services_ira():
    from .models import ConteoCiclico
    return ConteoCiclico.ira(desde=timezone.now() - timedelta(days=90))


@personal_planta_requerido
def planta_estado_json(request):
    """Polling del tablero (cada 5 s): últimos valores de cada equipo."""
    data = []
    for eq in Equipo.objects.all():
        vars_ = {}
        for v in eq.limites.keys():
            l = eq.ultima_lectura(v)
            if l:
                vars_[v] = {"valor": float(l.valor), "alerta": l.fuera_de_rango, "ts": l.timestamp.isoformat()}
        data.append({"codigo": eq.codigo, "estado": eq.estado, "llenado": eq.porcentaje_llenado,
                     "limites": eq.limites, "lecturas": vars_})
    return JsonResponse({"equipos": data, "ts": timezone.now().isoformat()})


# --------------------------------------------------------------------- WMS
@personal_planta_requerido
def wms(request):
    zona = request.GET.get("zona")
    ubicaciones = UbicacionWMS.objects.filter(activa=True).prefetch_related("existencias__lote__producto")
    if zona:
        ubicaciones = ubicaciones.filter(zona=zona)
    mov_form = MovimientoForm()
    rec_form = RecepcionMPForm()
    if not puede_editar_estacion(request.user, Estacion.ALMACEN):
        mov_form.bloquear()
    if not puede_editar_estacion(request.user, Estacion.RECEPCION):
        rec_form.bloquear()
    return render(request, "planta/wms.html", {
        "ubicaciones": ubicaciones, "zonas": Zona.choices, "zona_sel": zona,
        "mov_form": mov_form, "rec_form": rec_form,
        "kardex": MovimientoKardex.objects.select_related("lote__producto", "usuario")[:25],
        "puede_mover": puede_editar_estacion(request.user, Estacion.ALMACEN),
        "puede_recibir": puede_editar_estacion(request.user, Estacion.RECEPCION),
    })


@require_POST
@personal_planta_requerido
def wms_movimiento(request):
    form = MovimientoForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Movimiento inválido: {form.errors.as_text()}")
        return redirect("core:wms")
    d = form.cleaned_data
    try:
        services.registrar_movimiento(
            user=request.user, tipo=d["tipo"], lote=d["lote"], cantidad=d["cantidad"],
            ubicacion_origen=d.get("ubicacion_origen"), ubicacion_destino=d.get("ubicacion_destino"),
            motivo_merma=d.get("motivo_merma") or "", referencia=d.get("referencia") or "",
        )
        messages.success(request, "Movimiento registrado en Kardex.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, "; ".join(getattr(e, "messages", [str(e)])))
    return redirect("core:wms")


@require_POST
@personal_planta_requerido
def wms_recepcion(request):
    """Operario de Recepción: crea lote MP (FIFO) y registra la entrada."""
    if not puede_editar_estacion(request.user, Estacion.RECEPCION):
        raise PermissionDenied("Solo el operario de Recepción o el administrador registran recepciones.")
    form = RecepcionMPForm(request.POST)
    if not form.is_valid():
        messages.error(request, form.errors.as_text())
        return redirect("core:wms")
    d = form.cleaned_data
    with transaction.atomic():
        lote = Lote.objects.create(
            codigo=f"MP-{timezone.now():%y%m%d}-{uuid.uuid4().hex[:4].upper()}",
            producto=d["producto"], tipo=Lote.Tipo.MATERIA_PRIMA, cantidad_inicial=d["cantidad"],
            unidad=d["producto"].unidad_medida, proveedor=d["proveedor"],
            origen_geografico=d.get("origen_geografico", ""), fecha_caducidad=d.get("fecha_caducidad"),
            estacion_responsable=Estacion.RECEPCION, creado_por=request.user,
        )
        services.registrar_movimiento(user=request.user, tipo="ENTRADA", lote=lote, cantidad=d["cantidad"],
                                      ubicacion_destino=d["ubicacion"], referencia="Recepción",
                                      estacion=Estacion.RECEPCION)
        services.auditar(request.user, "CREAR", lote, detalle="Recepción de materia prima")
    messages.success(request, f"Lote {lote.codigo} recibido. Queda en CUARENTENA hasta registrar PC-1.")
    return redirect("core:wms")


@personal_planta_requerido
def picking_sugerido(request, codigo):
    """JSON con la propuesta FEFO/FIFO para un SKU y cantidad."""
    p = get_object_or_404(Producto, codigo=codigo)
    plan, faltante = services.sugerir_picking(p, request.GET.get("cantidad", "0") or "0")
    return JsonResponse({
        "sku": p.codigo, "regla": p.regla_rotacion, "faltante": float(faltante),
        "plan": [{"lote": x["lote"].codigo, "ubicacion": x["ubicacion"].codigo, "cantidad": float(x["cantidad"]),
                  "caduca": x["caduca"].isoformat() if x["caduca"] else None} for x in plan],
    })


# --------------------------------------------------------------------- MES / eBR
@personal_planta_requerido
def ordenes(request):
    qs = OrdenProduccion.objects.select_related("producto", "equipo")
    if request.GET.get("linea"):
        qs = qs.filter(linea=request.GET["linea"])
    return render(request, "planta/ordenes.html", {"ordenes": qs[:100]})


@personal_planta_requerido
def orden_detalle(request, pk):
    orden = get_object_or_404(OrdenProduccion.objects.select_related("producto", "equipo"), pk=pk)
    mi_est = estacion_de(request.user)
    form = RegistroEtapaForm(initial={"estacion": mi_est or orden.etapa_actual, "equipo": orden.equipo})
    corte_form = CorteDestilacionForm(initial={"alambique": orden.equipo if orden.equipo and orden.equipo.tipo == "ALAMBIQUE" else None})
    puede_registrar = es_admin(request.user) or bool(mi_est)
    if not puede_registrar:
        form.bloquear()
    if not puede_editar_estacion(request.user, Estacion.DESTILACION):
        corte_form.bloquear()
    serie = {}
    for l in orden.lecturas.order_by("timestamp")[:500]:
        serie.setdefault(l.variable, []).append([l.timestamp.isoformat(), float(l.valor)])
    return render(request, "planta/orden_detalle.html", {
        "orden": orden,
        "registros": orden.registros.select_related("registrado_por", "equipo", "lote").all(),
        "balance": orden.balance_materia(),
        "lotes": orden.lotes.all(),
        "form": form, "corte_form": corte_form,
        "puede_registrar": puede_registrar,
        "puede_pcc1": puede_editar_estacion(request.user, Estacion.DESTILACION),
        "serie_iot": serie,
    })


@require_POST
@personal_planta_requerido
def registrar_etapa(request, pk):
    orden = get_object_or_404(OrdenProduccion, pk=pk)
    form = RegistroEtapaForm(request.POST)
    if not form.is_valid():
        messages.error(request, form.errors.as_text())
        return redirect(orden.get_absolute_url())
    estacion = form.cleaned_data["estacion"]
    if not puede_editar_estacion(request.user, estacion):
        services.auditar(request.user, "DENEGADO", orden, detalle=f"Registro eBR en {estacion}",
                         estacion_objeto=estacion)
        raise PermissionDenied("Solo puede registrar etapas de su propia estación.")
    with transaction.atomic():
        reg = form.save(commit=False)
        reg.orden = orden
        reg.variables = form.cleaned_data["variables_texto"]
        reg.registrado_por = request.user
        reg.firmado = True
        if form.cleaned_data["control"] == "PCC-1":
            corte_form = CorteDestilacionForm(request.POST)
            if not corte_form.is_valid():
                messages.error(request, "PCC-1: " + corte_form.errors.as_text())
                return redirect(orden.get_absolute_url())
            reg.save()
            corte = corte_form.save(commit=False)
            corte.registro = reg
            corte.save()
            reg.refresh_from_db()
            if reg.lote_id and corte.conforme:
                Lote.objects.filter(pk=reg.lote_id).update(abv_final=corte.abv_corazon)
        else:
            reg.save()
        # consolida resultados de calidad en el lote
        if reg.lote_id and reg.control == "PC-2" and "humedad_final_pct" in reg.variables:
            Lote.objects.filter(pk=reg.lote_id).update(humedad_final_pct=reg.variables["humedad_final_pct"])
        if orden.estado == "PLAN":
            orden.estado, orden.fecha_inicio = "PROC", timezone.now()
        orden.etapa_actual = estacion
        orden.save(update_fields=["estado", "fecha_inicio", "etapa_actual"])
        services.auditar(request.user, "CREAR", reg, detalle=f"eBR {reg.control} conforme={reg.conforme}")
    if reg.conforme:
        messages.success(request, f"Etapa «{reg.etapa}» registrada y CONFORME.")
    else:
        messages.warning(request, "Registro guardado con DESVIACIONES: " + "; ".join(reg.desviaciones))
    return redirect(orden.get_absolute_url())


@require_POST
@admin_requerido
def aprobar_registro(request, pk):
    reg = get_object_or_404(RegistroEtapa, pk=pk)
    reg.aprobado_por, reg.fecha_aprobacion = request.user, timezone.now()
    reg.save(update_fields=["aprobado_por", "fecha_aprobacion"])
    services.auditar(request.user, "EDITAR", reg, cambios={"aprobado_por": [None, request.user.pk]},
                     detalle="Aprobación de registro eBR")
    return redirect(reg.orden.get_absolute_url())


@personal_planta_requerido
def lote_detalle(request, codigo):
    lote = get_object_or_404(Lote.objects.select_related("producto", "orden"), codigo=codigo)
    ok, motivos = lote.puede_liberarse()
    return render(request, "planta/lote_detalle.html", {
        "lote": lote, "liberable": ok, "motivos": motivos,
        "existencias": lote.existencias.select_related("ubicacion").filter(cantidad__gt=0),
        "movimientos": lote.movimientos.select_related("usuario")[:50],
        "unidades": lote.unidades.all()[:50], "total_unidades": lote.unidades.count(),
        "registros": lote.registros.all(),
    })


@require_POST
@admin_requerido
def lote_liberar(request, codigo):
    lote = get_object_or_404(Lote, codigo=codigo)
    accion = request.POST.get("accion", "liberar")
    try:
        if accion == "liberar":
            services.liberar_lote(request.user, lote, forzar=request.POST.get("forzar") == "1",
                                  motivo=request.POST.get("motivo", ""))
            messages.success(request, f"Lote {lote.codigo} LIBERADO.")
        else:
            services.retener_lote(request.user, lote, request.POST.get("motivo", "Sin motivo"),
                                  rechazar=accion == "rechazar")
            messages.warning(request, f"Lote {lote.codigo} {lote.get_estado_display()}.")
    except ValidationError as e:
        messages.error(request, "No liberable: " + "; ".join(e.messages))
    return redirect(lote.get_absolute_url())


# --------------------------------------------------------------------- Despacho CEDI
@personal_planta_requerido
def despachos(request):
    return render(request, "planta/despachos.html", {
        "despachos": Despacho.objects.annotate(n=Count("detalles"))[:50],
        "puede_editar": puede_editar_estacion(request.user, Estacion.ALMACEN),
    })


@personal_planta_requerido
def despacho_detalle(request, pk):
    d = get_object_or_404(Despacho, pk=pk)
    return render(request, "planta/despacho_detalle.html", {
        "d": d, "detalles": d.detalles.select_related("lote__producto", "ubicacion_origen"),
        "contrato": d.payload_enviado or services.construir_contrato_cedi(d),
        "puede_editar": puede_editar_estacion(request.user, Estacion.ALMACEN),
    })


@require_POST
@personal_planta_requerido
def despacho_accion(request, pk):
    d = get_object_or_404(Despacho, pk=pk)
    if not puede_editar_estacion(request.user, Estacion.ALMACEN):
        raise PermissionDenied("Solo Almacén/Despacho puede operar despachos.")
    accion = request.POST.get("accion")
    try:
        if accion == "pick":
            det = d.detalles.get(pk=request.POST["detalle"])
            det.pickeado = not det.pickeado
            det.save(update_fields=["pickeado"])
        elif accion == "confirmar":
            services.confirmar_despacho(request.user, d)
            messages.success(request, f"Despacho {d.codigo} enviado al CEDI ({d.get_estado_display()}).")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, "; ".join(getattr(e, "messages", [str(e)])))
    return redirect("core:despacho_detalle", pk=d.pk)


# =============================================================================
# MÓDULO 5 · REPORTES  (las descargas están en exports.py)
# =============================================================================
@personal_planta_requerido
def reportes(request):
    return render(request, "planta/reportes.html", {
        "lotes": Lote.objects.filter(tipo="PT").select_related("producto")[:40],
        "despachos": Despacho.objects.all()[:20],
        "ultimos_eventos": RegistroAuditoria.objects.all()[:15],
        "sobrescrituras": RegistroAuditoria.objects.filter(sobrescritura_admin=True).count(),
    })


# =============================================================================
# MÓDULO 6 · USUARIOS (solo administrador)
# =============================================================================
@admin_requerido
def usuarios(request):
    qs = User.objects.select_related("perfil").order_by("perfil__rol", "username")
    sesiones = (RegistroAuditoria.objects.filter(accion__in=["LOGIN", "LOGOUT", "LOGIN_KO"])[:30])
    return render(request, "planta/usuarios.html", {"usuarios": qs, "sesiones": sesiones})


@admin_requerido
def usuario_editar(request, pk=None):
    instancia = get_object_or_404(User, pk=pk) if pk else None
    form = UsuarioPlantaForm(request.POST or None, instance=instancia)
    if request.method == "POST" and form.is_valid():
        antes = services.snapshot(instancia.perfil) if instancia and hasattr(instancia, "perfil") else {}
        user = form.save()
        user.refresh_from_db()
        cambios = services.diff_campos(antes, services.snapshot(user.perfil))
        cambios.pop("id", None)
        services.auditar(request.user, "EDITAR" if instancia else "CREAR", user.perfil, cambios=cambios,
                         detalle="Gestión de usuarios" + (" · contraseña cambiada" if form.cleaned_data.get("password1") else ""))
        messages.success(request, f"Usuario {user.username} guardado.")
        return redirect("core:usuarios")
    return render(request, "planta/usuario_form.html", {"form": form, "instancia": instancia})


@require_POST
@admin_requerido
def usuario_toggle_estacion(request, pk):
    u = get_object_or_404(User.objects.select_related("perfil"), pk=pk)
    if u == request.user:
        messages.error(request, "No puede desactivarse a sí mismo.")
        return redirect("core:usuarios")
    u.perfil.estacion_activa = not u.perfil.estacion_activa
    u.perfil.save(update_fields=["estacion_activa"])
    services.auditar(request.user, "EDITAR", u.perfil,
                     cambios={"estacion_activa": [not u.perfil.estacion_activa, u.perfil.estacion_activa]})
    return redirect("core:usuarios")

"""
BAKELY · API REST (Django REST Framework)

  /api/catalogo/                 público, solo lectura (clientes)
  /api/trazabilidad/<token>/     público, visor QR
  /api/planta/...                personal de planta: lee todo, escribe solo su estación
  /api/iot/lecturas/             ESP32 / Node-RED (cabecera X-Device-Key)
  /api/cedi/despachos/<id>/contrato/   contrato JSON despacho_planta_hacia_cedi
  /api/cedi/confirmacion/        webhook de recepción desde el CEDI (token)
"""
import hmac
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied as DjPermissionDenied
from django.core.exceptions import ValidationError as DjValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from . import services
from .models import (
    Despacho, Equipo, Estacion, Existencia, LecturaIoT, Lote, MovimientoKardex, OrdenProduccion, Producto,
    RegistroAuditoria, RegistroEtapa, UbicacionWMS, UnidadSerializada,
)
from .permissions import (
    ClienteSoloLectura, EsAdministrador, EsPersonalPlanta, LecturaTodosEdicionPorEstacion, estacion_de,
)
from .serializers import (
    ConfirmacionCediSerializer, DespachoSerializer, EquipoSerializer, ExistenciaSerializer,
    LecturaIoTEntradaSerializer, LecturaIoTSerializer, LoteSerializer, MovimientoCrearSerializer,
    MovimientoKardexSerializer, OrdenProduccionSerializer, ProductoPublicoSerializer, ProductoSerializer,
    RegistroAuditoriaSerializer, RegistroEtapaSerializer, TrazabilidadPublicaSerializer, UbicacionSerializer,
    UnidadSerializadaSerializer,
)


def _dj_a_drf(exc):
    if isinstance(exc, DjPermissionDenied):
        return PermissionDenied(str(exc))
    if isinstance(exc, DjValidationError):
        return ValidationError(exc.messages)
    return exc


class AuditoriaViewSetMixin:
    """Registra en bitácora toda creación/edición/borrado hecho por la API."""

    def perform_create(self, serializer):
        obj = serializer.save(**self.extra_create_kwargs())
        services.auditar(self.request.user, "CREAR", obj, detalle="API")

    def perform_update(self, serializer):
        antes = services.snapshot(serializer.instance)
        obj = serializer.save()
        services.auditar(self.request.user, "EDITAR", obj, cambios=services.diff_campos(antes, services.snapshot(obj)),
                         detalle="API")

    def perform_destroy(self, instance):
        services.auditar(self.request.user, "ELIMINAR", instance, detalle="API")
        instance.delete()

    def extra_create_kwargs(self):
        return {}


# =============================================================================
# PÚBLICO
# =============================================================================
class CatalogoPublicoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductoPublicoSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle]
    lookup_field = "codigo"

    def get_queryset(self):
        qs = Producto.objects.filter(publicado_tienda=True, activo=True).select_related("categoria")
        linea = self.request.query_params.get("linea")
        return qs.filter(linea=linea) if linea else qs


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AnonRateThrottle])
def trazabilidad_publica(request, token):
    unidad = UnidadSerializada.objects.filter(qr_token=token).select_related("lote").first()
    lote = unidad.lote if unidad else get_object_or_404(Lote, qr_token=token, tipo="PT")
    data = TrazabilidadPublicaSerializer(lote).data
    if unidad:
        data["unidad"] = {"serial": unidad.serial, "sello_fiscal": unidad.sello_fiscal or None,
                          "envasado": unidad.fecha_envasado.isoformat()}
    return Response(data)


# =============================================================================
# PLANTA · "ven todo, editan su estación"
# =============================================================================
class ProductoViewSet(AuditoriaViewSetMixin, viewsets.ModelViewSet):
    """Maestro de productos: lectura para personal; escritura solo administrador."""
    queryset = Producto.objects.select_related("categoria")
    serializer_class = ProductoSerializer
    lookup_field = "codigo"

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [EsPersonalPlanta()]
        return [EsAdministrador()]


class UbicacionViewSet(AuditoriaViewSetMixin, viewsets.ModelViewSet):
    queryset = UbicacionWMS.objects.all()
    serializer_class = UbicacionSerializer
    permission_classes = [LecturaTodosEdicionPorEstacion]

    def estacion_para_creacion(self, request):
        return Estacion.ALMACEN


class ExistenciaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ExistenciaSerializer
    permission_classes = [EsPersonalPlanta]

    def get_queryset(self):
        qs = Existencia.objects.filter(cantidad__gt=0).select_related("lote__producto", "ubicacion")
        p = self.request.query_params
        if p.get("zona"):
            qs = qs.filter(ubicacion__zona=p["zona"])
        if p.get("sku"):
            qs = qs.filter(lote__producto__codigo=p["sku"])
        return qs


class KardexViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    viewsets.GenericViewSet):
    """El Kardex es inmutable: se crea vía services.registrar_movimiento, nunca se edita."""
    queryset = MovimientoKardex.objects.select_related("lote", "usuario")
    serializer_class = MovimientoKardexSerializer
    permission_classes = [EsPersonalPlanta]

    def create(self, request, *args, **kwargs):
        s = MovimientoCrearSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            mov = services.registrar_movimiento(user=request.user, **s.validated_data)
        except (DjPermissionDenied, DjValidationError) as e:
            raise _dj_a_drf(e)
        return Response(MovimientoKardexSerializer(mov).data, status=status.HTTP_201_CREATED)


class EquipoViewSet(AuditoriaViewSetMixin, viewsets.ModelViewSet):
    queryset = Equipo.objects.all()
    serializer_class = EquipoSerializer
    permission_classes = [LecturaTodosEdicionPorEstacion]
    lookup_field = "codigo"

    def estacion_para_creacion(self, request):
        return request.data.get("estacion")

    @action(detail=True, methods=["get"])
    def serie(self, request, codigo=None):
        """Serie temporal de una variable: /api/planta/equipos/TQ-01/serie/?variable=TEMP&horas=12"""
        eq = self.get_object()
        horas = int(request.query_params.get("horas", 12))
        qs = eq.lecturas.filter(variable=request.query_params.get("variable", "TEMP"),
                                timestamp__gte=timezone.now() - timedelta(hours=horas)).order_by("timestamp")
        return Response(LecturaIoTSerializer(qs[:2000], many=True).data)


class OrdenProduccionViewSet(AuditoriaViewSetMixin, viewsets.ModelViewSet):
    queryset = OrdenProduccion.objects.select_related("producto", "equipo")
    serializer_class = OrdenProduccionSerializer

    def get_permissions(self):
        # Crear/anular órdenes es planificación → administrador. Operarios: lectura.
        if self.request.method in permissions.SAFE_METHODS:
            return [EsPersonalPlanta()]
        return [EsAdministrador()]

    def extra_create_kwargs(self):
        return {"creada_por": self.request.user}

    @action(detail=True, methods=["get"])
    def balance(self, request, pk=None):
        return Response({k: (str(v) if v is not None else None)
                         for k, v in self.get_object().balance_materia().items()})


class LoteViewSet(AuditoriaViewSetMixin, viewsets.ModelViewSet):
    queryset = Lote.objects.select_related("producto")
    serializer_class = LoteSerializer
    permission_classes = [LecturaTodosEdicionPorEstacion]
    lookup_field = "codigo"

    def estacion_para_creacion(self, request):
        return request.data.get("estacion_responsable") or estacion_de(request.user)

    def extra_create_kwargs(self):
        return {"creado_por": self.request.user}

    @action(detail=True, methods=["post"], permission_classes=[EsAdministrador])
    def liberar(self, request, codigo=None):
        try:
            lote = services.liberar_lote(request.user, self.get_object(),
                                         forzar=bool(request.data.get("forzar")), motivo=request.data.get("motivo", ""))
        except (DjPermissionDenied, DjValidationError) as e:
            raise _dj_a_drf(e)
        return Response(LoteSerializer(lote).data)


class RegistroEtapaViewSet(AuditoriaViewSetMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                           mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """eBR: los registros son de solo inserción (sin update/delete) — integridad tipo 21 CFR Part 11."""
    queryset = RegistroEtapa.objects.select_related("orden", "registrado_por").prefetch_related("corte")
    serializer_class = RegistroEtapaSerializer
    permission_classes = [LecturaTodosEdicionPorEstacion]

    def estacion_para_creacion(self, request):
        return request.data.get("estacion")

    def extra_create_kwargs(self):
        return {"registrado_por": self.request.user, "firmado": True}


class UnidadSerializadaViewSet(AuditoriaViewSetMixin, viewsets.ModelViewSet):
    queryset = UnidadSerializada.objects.select_related("lote")
    serializer_class = UnidadSerializadaSerializer
    permission_classes = [LecturaTodosEdicionPorEstacion]
    lookup_field = "serial"

    def estacion_para_creacion(self, request):
        return Estacion.ENVASADO

    def extra_create_kwargs(self):
        return {"envasado_por": self.request.user}


class AuditoriaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RegistroAuditoria.objects.all()
    serializer_class = RegistroAuditoriaSerializer
    permission_classes = [EsAdministrador]


# =============================================================================
# IoT · ESP32 → MQTT → Node-RED → HTTP
# =============================================================================
class DispositivoIoTPermiso(permissions.BasePermission):
    """Autentica dispositivos por clave compartida (comparación en tiempo constante)."""

    def has_permission(self, request, view):
        clave = request.headers.get("X-Device-Key", "")
        esperado = settings.BAKELY.get("IOT_DEVICE_KEY", "")
        return bool(esperado) and hmac.compare_digest(clave, esperado)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([DispositivoIoTPermiso])
def iot_lecturas(request):
    """
    Acepta un objeto o una lista (lotes de Node-RED):
      POST /api/iot/lecturas/
      X-Device-Key: <IOT_DEVICE_KEY>
      [{"dispositivo":"esp32-tq01","variable":"ph","valor":3.95}, …]
    """
    datos = request.data if isinstance(request.data, list) else [request.data]
    if len(datos) > 500:
        raise ValidationError("Máximo 500 lecturas por petición.")
    s = LecturaIoTEntradaSerializer(data=datos, many=True)
    s.is_valid(raise_exception=True)
    guardadas, errores = [], []
    for i, d in enumerate(s.validated_data):
        try:
            l = services.procesar_lectura_iot(dispositivo=d["dispositivo"], variable=d["variable"],
                                              valor=d["valor"], timestamp=d.get("ts"),
                                              equipo_codigo=d.get("equipo"))
            guardadas.append({"id": l.id, "equipo": l.equipo.codigo, "alerta": l.fuera_de_rango})
        except DjValidationError as e:
            errores.append({"indice": i, "error": e.messages})
    code = status.HTTP_201_CREATED if guardadas else status.HTTP_400_BAD_REQUEST
    return Response({"guardadas": guardadas, "errores": errores}, status=code)


# =============================================================================
# CEDI
# =============================================================================
class DespachoViewSet(AuditoriaViewSetMixin, viewsets.ModelViewSet):
    queryset = Despacho.objects.prefetch_related("detalles")
    serializer_class = DespachoSerializer
    permission_classes = [LecturaTodosEdicionPorEstacion]

    def estacion_para_creacion(self, request):
        return Estacion.ALMACEN

    def extra_create_kwargs(self):
        return {"creado_por": self.request.user}

    @action(detail=True, methods=["get"])
    def contrato(self, request, pk=None):
        """GET /api/cedi/despachos/<id>/contrato/ → JSON despacho_planta_hacia_cedi"""
        d = self.get_object()
        return Response(d.payload_enviado or services.construir_contrato_cedi(d))

    @action(detail=True, methods=["post"])
    def confirmar(self, request, pk=None):
        try:
            d = services.confirmar_despacho(request.user, self.get_object(),
                                            enviar_api=request.data.get("enviar_api", True))
        except (DjPermissionDenied, DjValidationError) as e:
            raise _dj_a_drf(e)
        return Response({"estado": d.estado, "contrato": d.payload_enviado, "respuesta_cedi": d.respuesta_cedi})


class TokenCediPermiso(permissions.BasePermission):
    def has_permission(self, request, view):
        auth = request.headers.get("Authorization", "")
        esperado = settings.BAKELY.get("CEDI_API_TOKEN", "")
        return bool(esperado) and hmac.compare_digest(auth, f"Bearer {esperado}")


@api_view(["POST"])
@authentication_classes([])
@permission_classes([TokenCediPermiso])
def cedi_confirmacion(request):
    """Webhook: el CEDI confirma recepción física (y reporta diferencias si las hay)."""
    s = ConfirmacionCediSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    d = get_object_or_404(Despacho, codigo=s.validated_data["codigo_despacho"])
    d.estado = Despacho.Estado.CONFIRMADO
    d.respuesta_cedi = {**(d.respuesta_cedi or {}), "confirmacion": request.data}
    d.save(update_fields=["estado", "respuesta_cedi"])
    services.auditar(None, "API", d, detalle=f"Confirmación CEDI · diferencias={len(s.validated_data.get('diferencias', []))}")
    return Response({"ok": True, "despacho": d.codigo, "estado": d.estado})

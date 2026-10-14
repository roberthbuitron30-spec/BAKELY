"""BAKELY · Serializadores DRF (API interna, IoT, CEDI y catálogo público)."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .models import (
    Categoria, CorteDestilacion, Despacho, DetalleDespacho, Equipo, Existencia, LecturaIoT, Lote,
    MovimientoKardex, OrdenProduccion, Producto, RegistroAuditoria, RegistroEtapa, UbicacionWMS,
    UnidadSerializada,
)


# --------------------------------------------------------------------- Catálogo
class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ["id", "nombre", "slug", "tipo", "linea", "icono"]


class ProductoPublicoSerializer(serializers.ModelSerializer):
    """Vista de cliente: sin costos, stock mínimo ni IDs de Odoo."""
    categoria = CategoriaSerializer(read_only=True)
    imagen_url = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = [
            "codigo", "nombre", "categoria", "linea", "imagen_url", "imagen_alt", "descripcion_corta",
            "descripcion_tecnica", "flujo_operativo", "parametros_tecnicos", "presentacion",
            "contenido_neto", "unidad_medida", "graduacion_abv", "alergenos", "notas_sensoriales",
            "usos_recomendados", "precio_venta", "requiere_mayoria_edad",
        ]

    def get_imagen_url(self, obj):
        if not obj.imagen:
            return None
        req = self.context.get("request")
        return req.build_absolute_uri(obj.imagen.url) if req else obj.imagen.url


class ProductoSerializer(serializers.ModelSerializer):
    stock_total = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)

    class Meta:
        model = Producto
        fields = "__all__"


# --------------------------------------------------------------------- WMS
class UbicacionSerializer(serializers.ModelSerializer):
    estacion_responsable = serializers.CharField(read_only=True)

    class Meta:
        model = UbicacionWMS
        fields = "__all__"


class ExistenciaSerializer(serializers.ModelSerializer):
    lote_codigo = serializers.CharField(source="lote.codigo", read_only=True)
    producto = serializers.CharField(source="lote.producto.codigo", read_only=True)
    ubicacion_codigo = serializers.CharField(source="ubicacion.codigo", read_only=True)
    caducidad = serializers.DateField(source="lote.fecha_caducidad", read_only=True)

    class Meta:
        model = Existencia
        fields = ["id", "lote", "lote_codigo", "producto", "ubicacion", "ubicacion_codigo", "cantidad", "caducidad"]


class MovimientoKardexSerializer(serializers.ModelSerializer):
    usuario = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = MovimientoKardex
        fields = "__all__"
        read_only_fields = ["saldo_lote", "usuario", "unidad", "fecha"]


class MovimientoCrearSerializer(serializers.Serializer):
    """Entrada para services.registrar_movimiento."""
    tipo = serializers.ChoiceField(choices=MovimientoKardex.Tipo.choices)
    lote = serializers.PrimaryKeyRelatedField(queryset=Lote.objects.all())
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    ubicacion_origen = serializers.PrimaryKeyRelatedField(queryset=UbicacionWMS.objects.all(), required=False, allow_null=True)
    ubicacion_destino = serializers.PrimaryKeyRelatedField(queryset=UbicacionWMS.objects.all(), required=False, allow_null=True)
    orden = serializers.PrimaryKeyRelatedField(queryset=OrdenProduccion.objects.all(), required=False, allow_null=True)
    motivo_merma = serializers.ChoiceField(choices=MovimientoKardex.MotivoMerma.choices, required=False, allow_blank=True)
    referencia = serializers.CharField(required=False, allow_blank=True, max_length=80)


# --------------------------------------------------------------------- MES / eBR
class EquipoSerializer(serializers.ModelSerializer):
    porcentaje_llenado = serializers.IntegerField(read_only=True)
    ultimas = serializers.SerializerMethodField()

    class Meta:
        model = Equipo
        fields = "__all__"

    def get_ultimas(self, obj):
        out = {}
        for var in obj.limites.keys() or ["TEMP"]:
            l = obj.ultima_lectura(var)
            if l:
                out[var] = {"valor": float(l.valor), "ts": l.timestamp.isoformat(), "alerta": l.fuera_de_rango}
        return out


class OrdenProduccionSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    balance = serializers.SerializerMethodField()

    class Meta:
        model = OrdenProduccion
        fields = "__all__"
        read_only_fields = ["creada_por"]

    def get_balance(self, obj):
        return {k: (float(v) if v is not None else None) for k, v in obj.balance_materia().items()}


class LoteSerializer(serializers.ModelSerializer):
    stock_actual = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)

    class Meta:
        model = Lote
        fields = "__all__"
        read_only_fields = ["estado", "liberado_por", "fecha_liberacion", "qr_token", "creado_por", "pcc1_conforme"]


class CorteDestilacionSerializer(serializers.ModelSerializer):
    lap_carga = serializers.DecimalField(max_digits=10, decimal_places=3, read_only=True)
    lap_corazon = serializers.DecimalField(max_digits=10, decimal_places=3, read_only=True)

    class Meta:
        model = CorteDestilacion
        exclude = ["registro"]
        read_only_fields = ["conforme", "motivos_no_conformidad"]


class RegistroEtapaSerializer(serializers.ModelSerializer):
    corte = CorteDestilacionSerializer(required=False)
    registrado_por = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = RegistroEtapa
        fields = "__all__"
        read_only_fields = ["conforme", "desviaciones", "registrado_por", "firmado", "aprobado_por", "fecha_aprobacion"]

    def validate(self, attrs):
        if attrs.get("control") == "PCC-1" and not attrs.get("corte"):
            raise serializers.ValidationError({"corte": "PCC-1 exige el detalle de cortes de destilación."})
        return attrs

    def create(self, validated_data):
        corte = validated_data.pop("corte", None)
        reg = RegistroEtapa.objects.create(**validated_data)
        if corte:
            CorteDestilacion.objects.create(registro=reg, **corte)
            reg.refresh_from_db()
        return reg


class UnidadSerializadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnidadSerializada
        fields = "__all__"
        read_only_fields = ["qr_token", "envasado_por"]


# --------------------------------------------------------------------- IoT (ESP32 / Node-RED)
class LecturaIoTEntradaSerializer(serializers.Serializer):
    """
    Formato aceptado (individual o lista):
    {"dispositivo": "esp32-tq01", "variable": "temperatura", "valor": 24.3, "ts": "2026-10-13T10:00:00-05:00"}
    Opcional: "equipo": "TQ-01" si el dispositivo publica para varios equipos.
    """
    dispositivo = serializers.CharField(max_length=40)
    variable = serializers.CharField(max_length=20)
    valor = serializers.DecimalField(max_digits=10, decimal_places=4)
    ts = serializers.DateTimeField(required=False)
    equipo = serializers.CharField(required=False, max_length=20)

    def validate_ts(self, value):
        if value and value > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError("Marca de tiempo en el futuro (revise el RTC del ESP32).")
        return value


class LecturaIoTSerializer(serializers.ModelSerializer):
    equipo = serializers.CharField(source="equipo.codigo")

    class Meta:
        model = LecturaIoT
        fields = ["id", "equipo", "variable", "valor", "timestamp", "fuera_de_rango", "dispositivo"]


# --------------------------------------------------------------------- Despacho CEDI
class DetalleDespachoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DetalleDespacho
        exclude = ["despacho"]


class DespachoSerializer(serializers.ModelSerializer):
    detalles = DetalleDespachoSerializer(many=True, required=False)

    class Meta:
        model = Despacho
        fields = "__all__"
        read_only_fields = ["estado", "fecha_envio", "creado_por", "payload_enviado", "respuesta_cedi"]

    def create(self, validated_data):
        detalles = validated_data.pop("detalles", [])
        desp = Despacho.objects.create(**validated_data)
        for d in detalles:
            DetalleDespacho.objects.create(despacho=desp, **d)
        return desp


class ConfirmacionCediSerializer(serializers.Serializer):
    """Webhook de vuelta: el CEDI confirma la recepción física."""
    codigo_despacho = serializers.CharField()
    recibido_en = serializers.DateTimeField()
    diferencias = serializers.ListField(child=serializers.DictField(), required=False)
    recibido_por = serializers.CharField(required=False)


# --------------------------------------------------------------------- Auditoría
class RegistroAuditoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegistroAuditoria
        fields = "__all__"


# --------------------------------------------------------------------- Trazabilidad pública
class TrazabilidadPublicaSerializer(serializers.Serializer):
    """Lo que ve un consumidor al escanear el QR: nada de datos internos sensibles."""

    def to_representation(self, lote: Lote):
        p = lote.producto
        origenes = [
            {"materia_prima": o.producto.nombre, "lote": o.codigo, "procedencia": o.origen_geografico or None,
             "productor": o.proveedor or None, "recibido": o.fecha_elaboracion.isoformat()}
            for o in lote.lotes_origen.select_related("producto")
        ]
        hitos = [
            {"etapa": r.etapa, "fecha": r.fecha.isoformat(), "control": r.control, "conforme": r.conforme}
            for r in lote.registros.order_by("fecha")
        ]
        return {
            "producto": p.nombre, "sku": p.codigo, "lote": lote.codigo,
            "estado": lote.get_estado_display(),
            "elaborado": lote.fecha_elaboracion.isoformat(),
            "caduca": lote.fecha_caducidad.isoformat() if lote.fecha_caducidad else None,
            "abv": float(lote.abv_final) if lote.abv_final is not None else None,
            "humedad_pct": float(lote.humedad_final_pct) if lote.humedad_final_pct is not None else None,
            "pcc1_conforme": lote.pcc1_conforme,
            "certificado_inocuidad": lote.certificado_inocuidad or None,
            "origen": origenes,
            "proceso": hitos,
        }

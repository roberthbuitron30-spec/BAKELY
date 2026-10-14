"""
BAKELY · Modelos de datos (WMS / MES / eBR / Trazabilidad)
Planta de Almidones y Licores — UPEC

Organización:
  1. Catálogos: Estación, Rol, PerfilUsuario, Categoría, Producto
  2. WMS: UbicacionWMS, Existencia, MovimientoKardex, ConteoCiclico
  3. MES / eBR: Equipo (tanque/alambique/secador), OrdenProduccion, Lote,
     UnidadSerializada, RegistroEtapa, CorteDestilacion (PCC-1), LecturaIoT
  4. Logística: Despacho, DetalleDespacho (contrato CEDI)
  5. Comercio: Pedido, DetallePedido
  6. Auditoría: RegistroAuditoria
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

# =============================================================================
# 1. CATÁLOGOS BASE
# =============================================================================


class Estacion(models.TextChoices):
    """Estaciones de trabajo. Cada operario edita SOLO la suya."""
    RECEPCION = "RECEPCION", "Recepción, Lavado y Molienda"
    ALMIDONES = "ALMIDONES", "Almidones (Extracción y Secado)"
    FERMENTACION = "FERMENTACION", "Fermentación (IoT / Tanques)"
    DESTILACION = "DESTILACION", "Destilación y Licores (PCC-1)"
    ENVASADO = "ENVASADO", "Envasado y Etiquetado"
    ALMACEN = "ALMACEN", "Almacén WMS y Despacho"


class Rol(models.TextChoices):
    CLIENTE = "CLIENTE", "Cliente / Consumidor"
    OPERARIO = "OPERARIO", "Operario de Planta"
    ADMIN = "ADMIN", "Administrador General"


class Linea(models.TextChoices):
    ALMIDON = "ALMIDON", "Línea A · Almidones"
    BEBIDA = "BEBIDA", "Línea B · Licores y Bebidas"
    COMUN = "COMUN", "Común / Ambas líneas"


class PerfilUsuario(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.CLIENTE)
    estacion = models.CharField(
        max_length=15, choices=Estacion.choices, blank=True,
        help_text="Estación asignada. Solo aplica a operarios.",
    )
    estacion_activa = models.BooleanField(
        default=True, help_text="Si está desactivada, el operario queda en solo lectura."
    )
    codigo_empleado = models.CharField(max_length=20, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    cedula = models.CharField("Cédula", max_length=13, blank=True)
    ultimo_cambio_clave = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Perfil de usuario"
        verbose_name_plural = "Perfiles de usuario"

    def __str__(self):
        return f"{self.usuario.get_full_name() or self.usuario.username} · {self.get_rol_display()}"

    @property
    def es_admin(self):
        return self.rol == Rol.ADMIN or self.usuario.is_superuser

    @property
    def es_operario(self):
        return self.rol == Rol.OPERARIO

    def clean(self):
        if self.rol == Rol.OPERARIO and not self.estacion:
            raise ValidationError({"estacion": "Un operario debe tener una estación asignada."})


class Categoria(models.Model):
    class Tipo(models.TextChoices):
        MATERIA_PRIMA = "MP", "Materia prima"
        INSUMO = "INS", "Insumo"
        EMPAQUE = "EMP", "Material de empaque"
        PRODUCTO_TERMINADO = "PT", "Producto terminado"
        INTERMEDIO = "INT", "Producto en proceso"

    nombre = models.CharField(max_length=80)
    slug = models.SlugField(unique=True)
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    linea = models.CharField(max_length=10, choices=Linea.choices, default=Linea.COMUN)
    descripcion = models.TextField(blank=True)
    icono = models.CharField(max_length=40, default="box", help_text="Nombre de icono Lucide")
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden", "nombre"]
        verbose_name = "Categoría"

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    """Ítem del catálogo: materia prima, insumo, empaque o producto terminado."""

    class Unidad(models.TextChoices):
        KG = "kg", "Kilogramo"
        L = "L", "Litro"
        UND = "und", "Unidad"
        SACO = "saco", "Saco"
        BOT = "bot", "Botella"

    class Rotacion(models.TextChoices):
        FEFO = "FEFO", "FEFO · primero en caducar, primero en salir"
        FIFO = "FIFO", "FIFO · primero en entrar, primero en salir"

    codigo = models.CharField("Código SKU", max_length=20, unique=True)
    nombre = models.CharField(max_length=120)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name="productos")
    linea = models.CharField(max_length=10, choices=Linea.choices)
    imagen = models.ImageField(
        upload_to="productos/%Y/", blank=True, null=True,
        help_text="Fotografía real del producto (recomendado 1200×900 px, JPG/WebP).",
    )
    imagen_alt = models.CharField("Texto alternativo de la imagen", max_length=200, blank=True)
    descripcion_corta = models.CharField(max_length=240, blank=True)
    descripcion_tecnica = models.TextField(blank=True)
    flujo_operativo = models.JSONField(
        default=list, blank=True,
        help_text='Lista ordenada de etapas, p. ej. ["Recepción", "Análisis PC-1", "Lavado/Rallado"]',
    )
    parametros_tecnicos = models.JSONField(
        default=dict, blank=True,
        help_text='Especificación, p. ej. {"humedad_max_pct": 12, "cenizas_max_pct": 0.5}',
    )
    unidad_medida = models.CharField(max_length=5, choices=Unidad.choices, default=Unidad.KG)
    contenido_neto = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
        help_text="Contenido por unidad de venta (25 kg, 0.750 L, 0.330 L).",
    )
    presentacion = models.CharField(max_length=120, blank=True)
    graduacion_abv = models.DecimalField(
        "Graduación alcohólica (% ABV)", max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(96)],
    )
    alergenos = models.CharField(max_length=200, blank=True)
    notas_sensoriales = models.TextField(blank=True, help_text="Notas de cata (bebidas) o pureza/uso (almidones).")
    usos_recomendados = models.TextField(blank=True)
    precio_venta = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vida_util_dias = models.PositiveIntegerField(null=True, blank=True)
    regla_rotacion = models.CharField(max_length=4, choices=Rotacion.choices, default=Rotacion.FIFO)
    zona_wms_default = models.CharField(max_length=20, blank=True, help_text="Zona de almacenamiento por defecto.")
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    estacion_responsable = models.CharField(max_length=15, choices=Estacion.choices, default=Estacion.ALMACEN)
    publicado_tienda = models.BooleanField(default=False)
    requiere_mayoria_edad = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    odoo_product_id = models.PositiveIntegerField(null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["categoria__orden", "codigo"]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"

    @property
    def es_bebida_alcoholica(self):
        return bool(self.graduacion_abv and self.graduacion_abv > Decimal("0.5"))

    @property
    def es_producto_terminado(self):
        return self.categoria.tipo == Categoria.Tipo.PRODUCTO_TERMINADO

    def stock_total(self):
        agg = Existencia.objects.filter(lote__producto=self).aggregate(t=models.Sum("cantidad"))
        return agg["t"] or Decimal("0")

    def get_absolute_url(self):
        return reverse("core:producto_detalle", args=[self.codigo])


# =============================================================================
# 2. WMS · UBICACIONES, EXISTENCIAS Y KARDEX
# =============================================================================


class Zona(models.TextChoices):
    REC = "ZONA-REC", "Recepción y pesaje de tubérculos"
    TANQUES = "ZONA-TANQUES", "Sala de fermentación"
    DEST = "ZONA-DEST", "Alambiques y destilación"
    SEC = "ZONA-SEC", "Túnel de secado de almidones"
    ALM_SECOS = "ZONA-ALM-SECOS", "Bodega de sacos de almidón"
    LIC_PT = "ZONA-LIC-PT", "Bodega de licores (acceso controlado)"
    FRIO = "ZONA-FRIO", "Almacén frío de insumos"
    EMP = "ZONA-EMP", "Bodega de empaques"
    MER = "ZONA-MER", "Mermas, pulpa y cabezas/colas"
    DESP = "ZONA-DESP", "Andén de despacho al CEDI"


ZONA_ESTACION = {
    Zona.REC: Estacion.RECEPCION,
    Zona.TANQUES: Estacion.FERMENTACION,
    Zona.DEST: Estacion.DESTILACION,
    Zona.SEC: Estacion.ALMIDONES,
    Zona.ALM_SECOS: Estacion.ALMACEN,
    Zona.LIC_PT: Estacion.ALMACEN,
    Zona.FRIO: Estacion.ALMACEN,
    Zona.EMP: Estacion.ALMACEN,
    Zona.MER: Estacion.ALMACEN,
    Zona.DESP: Estacion.ALMACEN,
}


class UbicacionWMS(models.Model):
    """Ubicación física codificada ZONA-RACK-NIVEL-POSICION (impresa como código de barras/QR)."""

    zona = models.CharField(max_length=20, choices=Zona.choices)
    rack = models.CharField(max_length=4, default="R01")
    nivel = models.CharField(max_length=3, default="N1")
    posicion = models.CharField(max_length=4, default="P01")
    codigo = models.CharField(max_length=40, unique=True, editable=False)
    descripcion = models.CharField(max_length=120, blank=True)
    capacidad = models.DecimalField(max_digits=12, decimal_places=3, default=0, help_text="En unidad de la zona")
    unidad_capacidad = models.CharField(max_length=10, default="kg")
    acceso_restringido = models.BooleanField(default=False)
    temperatura_controlada = models.BooleanField(default=False)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["zona", "rack", "nivel", "posicion"]
        verbose_name = "Ubicación WMS"
        verbose_name_plural = "Ubicaciones WMS"
        constraints = [
            models.UniqueConstraint(fields=["zona", "rack", "nivel", "posicion"], name="ubicacion_unica"),
        ]

    def save(self, *args, **kwargs):
        self.codigo = f"{self.zona}-{self.rack}-{self.nivel}-{self.posicion}"
        if self.zona == Zona.LIC_PT:
            self.acceso_restringido = True
        super().save(*args, **kwargs)

    def __str__(self):
        return self.codigo

    @property
    def estacion_responsable(self):
        return ZONA_ESTACION.get(self.zona, Estacion.ALMACEN)

    def ocupacion(self):
        total = self.existencias.aggregate(t=models.Sum("cantidad"))["t"] or Decimal("0")
        if not self.capacidad:
            return total, None
        return total, round(total / self.capacidad * 100, 1)


# =============================================================================
# 3. MES · EQUIPOS, ÓRDENES, LOTES, eBR, IoT
# =============================================================================


class Equipo(models.Model):
    """Tanque de fermentación, alambique, secador, rallador, llenadora…"""

    class Tipo(models.TextChoices):
        TANQUE = "TANQUE", "Tanque de fermentación"
        ALAMBIQUE = "ALAMBIQUE", "Alambique fraccionado"
        SECADOR = "SECADOR", "Secador / túnel"
        RALLADOR = "RALLADOR", "Ralladora / desintegrador"
        SEDIMENTADOR = "SEDIMENT", "Sedimentador / centrífuga"
        MACERADOR = "MACERADOR", "Tanque de maceración"
        LLENADORA = "LLENADORA", "Llenadora / envasadora"

    class EstadoEquipo(models.TextChoices):
        LIBRE = "LIBRE", "Libre"
        OPERANDO = "OPERANDO", "Operando"
        ALERTA = "ALERTA", "En alerta"
        LIMPIEZA = "LIMPIEZA", "En limpieza (CIP)"
        MANTENIMIENTO = "MANT", "Mantenimiento"

    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=80)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    estacion = models.CharField(max_length=15, choices=Estacion.choices)
    ubicacion = models.ForeignKey(UbicacionWMS, on_delete=models.SET_NULL, null=True, blank=True)
    capacidad = models.DecimalField(max_digits=10, decimal_places=2, help_text="Litros o kg")
    unidad_capacidad = models.CharField(max_length=5, default="L")
    nivel_actual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado = models.CharField(max_length=10, choices=EstadoEquipo.choices, default=EstadoEquipo.LIBRE)
    dispositivo_iot = models.CharField(
        max_length=40, blank=True, help_text="ID del ESP32 (coincide con el tópico MQTT)."
    )
    limites = models.JSONField(
        default=dict, blank=True,
        help_text='Rangos por variable, p. ej. {"TEMP": [22, 26], "PH": [3.8, 4.2]}',
    )

    class Meta:
        ordering = ["estacion", "codigo"]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"

    @property
    def estacion_responsable(self):
        return self.estacion

    @property
    def porcentaje_llenado(self):
        if not self.capacidad:
            return 0
        return min(100, round(float(self.nivel_actual) / float(self.capacidad) * 100))

    def ultima_lectura(self, variable):
        return self.lecturas.filter(variable=variable).order_by("-timestamp").first()

    def fuera_de_rango(self, variable, valor):
        rango = self.limites.get(variable)
        if not rango or len(rango) != 2:
            return False
        lo, hi = rango
        return not (Decimal(str(lo)) <= Decimal(str(valor)) <= Decimal(str(hi)))


class OrdenProduccion(models.Model):
    class Estado(models.TextChoices):
        PLANIFICADA = "PLAN", "Planificada"
        EN_PROCESO = "PROC", "En proceso"
        PAUSADA = "PAUSA", "Pausada"
        CERRADA = "CERRADA", "Cerrada"
        ANULADA = "ANULADA", "Anulada"

    codigo = models.CharField(max_length=24, unique=True)
    linea = models.CharField(max_length=10, choices=Linea.choices)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="ordenes")
    cantidad_planificada = models.DecimalField(max_digits=12, decimal_places=3)
    unidad = models.CharField(max_length=5, default="kg")
    estado = models.CharField(max_length=8, choices=Estado.choices, default=Estado.PLANIFICADA)
    etapa_actual = models.CharField(max_length=15, choices=Estacion.choices, default=Estacion.RECEPCION)
    equipo = models.ForeignKey(Equipo, on_delete=models.SET_NULL, null=True, blank=True, related_name="ordenes")
    fecha_planificada = models.DateField(default=timezone.localdate)
    fecha_inicio = models.DateTimeField(null=True, blank=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ordenes_creadas")
    odoo_mrp_id = models.PositiveIntegerField(null=True, blank=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha_planificada", "-id"]
        verbose_name = "Orden de producción"
        verbose_name_plural = "Órdenes de producción"

    def __str__(self):
        return f"{self.codigo} · {self.producto.nombre}"

    @property
    def estacion_responsable(self):
        return self.etapa_actual

    def get_absolute_url(self):
        return reverse("core:orden_detalle", args=[self.pk])

    # ---------------------------------------------------------- balance de materia
    def balance_materia(self):
        """
        Línea A: kg de tubérculo consumido vs kg de almidón seco producido (rendimiento %).
        Línea B: litros de alcohol puro (LAP) cargados al alambique vs LAP recuperados en corazón.
        """
        movs = self.movimientos.all()
        sum_tipo = lambda t: movs.filter(tipo=t).aggregate(s=models.Sum("cantidad"))["s"] or Decimal("0")
        entrada = sum_tipo(MovimientoKardex.Tipo.CONSUMO)
        salida = sum_tipo(MovimientoKardex.Tipo.PRODUCCION)
        merma = sum_tipo(MovimientoKardex.Tipo.MERMA)
        resultado = {
            "entrada": entrada,
            "salida": salida,
            "merma": merma,
            "no_contabilizado": entrada - salida - merma if self.linea == Linea.ALMIDON else None,
            "rendimiento_pct": round(salida / entrada * 100, 2) if entrada else None,
        }
        if self.linea == Linea.BEBIDA:
            cortes = CorteDestilacion.objects.filter(registro__orden=self)
            lap_in = sum((c.lap_carga for c in cortes), Decimal("0"))
            lap_cor = sum((c.lap_corazon for c in cortes), Decimal("0"))
            lap_out = sum((c.lap_total_fracciones for c in cortes), Decimal("0"))
            resultado.update({
                "lap_carga": round(lap_in, 3),
                "lap_corazon": round(lap_cor, 3),
                "lap_fracciones": round(lap_out, 3),
                "recuperacion_corazon_pct": round(lap_cor / lap_in * 100, 2) if lap_in else None,
                "perdida_lap_pct": round((lap_in - lap_out) / lap_in * 100, 2) if lap_in else None,
            })
        return resultado


class Lote(models.Model):
    class Tipo(models.TextChoices):
        MATERIA_PRIMA = "MP", "Lote de materia prima / insumo"
        INTERMEDIO = "INT", "Lote intermedio (mosto, lechada, destilado base)"
        TERMINADO = "PT", "Lote de producto terminado"

    class Estado(models.TextChoices):
        CUARENTENA = "CUARENTENA", "Cuarentena"
        LIBERADO = "LIBERADO", "Liberado"
        RETENIDO = "RETENIDO", "Retenido (no conforme)"
        RECHAZADO = "RECHAZADO", "Rechazado"
        AGOTADO = "AGOTADO", "Agotado / despachado"

    codigo = models.CharField(max_length=30, unique=True)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="lotes")
    orden = models.ForeignKey(OrdenProduccion, on_delete=models.PROTECT, null=True, blank=True, related_name="lotes")
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    lotes_origen = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="lotes_derivados",
        help_text="Genealogía: lotes de materia prima/intermedios que originaron este lote.",
    )
    cantidad_inicial = models.DecimalField(max_digits=12, decimal_places=3)
    unidad = models.CharField(max_length=5, default="kg")
    fecha_elaboracion = models.DateField(default=timezone.localdate)
    fecha_caducidad = models.DateField(null=True, blank=True)
    proveedor = models.CharField(max_length=120, blank=True, help_text="Para lotes MP: productor / asociación.")
    origen_geografico = models.CharField(max_length=120, blank=True, help_text="Parroquia / cantón de origen.")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.CUARENTENA)
    # Resultados de calidad consolidados (se llenan desde eBR)
    humedad_final_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cenizas_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    abv_final = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    pcc1_conforme = models.BooleanField(null=True, blank=True, help_text="Resultado de PCC-1 (bebidas destiladas).")
    certificado_inocuidad = models.CharField(max_length=60, blank=True)
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    liberado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="lotes_liberados"
    )
    fecha_liberacion = models.DateTimeField(null=True, blank=True)
    estacion_responsable = models.CharField(max_length=15, choices=Estacion.choices, default=Estacion.RECEPCION)
    creado = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lotes_creados")

    class Meta:
        ordering = ["-fecha_elaboracion", "-id"]
        indexes = [models.Index(fields=["producto", "fecha_caducidad"]), models.Index(fields=["estado"])]

    def __str__(self):
        return self.codigo

    def get_absolute_url(self):
        return reverse("core:lote_detalle", args=[self.codigo])

    @property
    def stock_actual(self):
        return self.existencias.aggregate(t=models.Sum("cantidad"))["t"] or Decimal("0")

    @property
    def dias_para_caducar(self):
        if not self.fecha_caducidad:
            return None
        return (self.fecha_caducidad - timezone.localdate()).days

    def puede_liberarse(self):
        """Devuelve (bool, motivos) según especificación del producto."""
        motivos = []
        spec = self.producto.parametros_tecnicos or {}
        if self.tipo == Lote.Tipo.TERMINADO:
            if "humedad_max_pct" in spec:
                if self.humedad_final_pct is None:
                    motivos.append("Falta humedad final (PC-2).")
                elif self.humedad_final_pct > Decimal(str(spec["humedad_max_pct"])):
                    motivos.append(f"Humedad {self.humedad_final_pct}% > {spec['humedad_max_pct']}%.")
            if "cenizas_max_pct" in spec and self.cenizas_pct is not None:
                if self.cenizas_pct > Decimal(str(spec["cenizas_max_pct"])):
                    motivos.append(f"Cenizas {self.cenizas_pct}% > {spec['cenizas_max_pct']}%.")
            if self.producto.categoria.slug.startswith("licor") or spec.get("requiere_pcc1"):
                if self.pcc1_conforme is not True:
                    motivos.append("PCC-1 de destilación no conforme o sin registrar.")
            if self.producto.graduacion_abv and self.abv_final is not None:
                tol = Decimal(str(spec.get("tolerancia_abv", 0.5)))
                if abs(self.abv_final - self.producto.graduacion_abv) > tol:
                    motivos.append(
                        f"ABV {self.abv_final}% fuera de ±{tol} respecto a {self.producto.graduacion_abv}%."
                    )
        return (len(motivos) == 0, motivos)


class UnidadSerializada(models.Model):
    """Cada botella o saco con número de serie y QR propio (trazabilidad unitaria)."""

    class Estado(models.TextChoices):
        EN_BODEGA = "BODEGA", "En bodega"
        DESPACHADA = "DESPACHO", "Despachada al CEDI"
        VENDIDA = "VENDIDA", "Vendida"
        BLOQUEADA = "BLOQUEO", "Bloqueada (retiro)"

    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, related_name="unidades")
    serial = models.CharField(max_length=40, unique=True)
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sello_fiscal = models.CharField(max_length=40, blank=True, help_text="Sello / timbre fiscal (bebidas).")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.EN_BODEGA)
    ubicacion = models.ForeignKey(UbicacionWMS, on_delete=models.SET_NULL, null=True, blank=True)
    envasado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    fecha_envasado = models.DateTimeField(default=timezone.now)
    escaneado_en_despacho = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Unidad serializada"
        verbose_name_plural = "Unidades serializadas"

    def __str__(self):
        return self.serial

    @property
    def estacion_responsable(self):
        return Estacion.ENVASADO


# --------------------------------------------------------------- Controles de calidad
class ControlCalidad(models.TextChoices):
    PC1 = "PC-1", "PC-1 · Recepción de tubérculos"
    PC2 = "PC-2", "PC-2 · Secado de almidón"
    PC3 = "PC-3", "PC-3 · Inoculación de mosto"
    PCC1 = "PCC-1", "PCC-1 · Cortes de destilación"
    GENERAL = "GEN", "Registro general de etapa"


# Especificación de cada control: variable → (mín, máx, unidad). None = sin límite.
ESPECIFICACION_CONTROLES = {
    "PC-1": {
        "humedad_pct": (None, 82, "%"),
        "impurezas_pct": (None, 3, "%"),
        "materia_seca_pct": (18, None, "%"),
    },
    "PC-2": {
        "temp_secado_c": (45, 50, "°C"),
        "humedad_final_pct": (None, 12, "%"),
    },
    "PC-3": {
        "brix_inicial": (14, 24, "°Bx"),
        "ph": (Decimal("3.8"), Decimal("4.2"), "pH"),
        "temp_c": (22, 26, "°C"),
    },
}


class RegistroEtapa(models.Model):
    """Entrada del Registro Electrónico de Lote (eBR). Inmutable una vez firmada."""

    orden = models.ForeignKey(OrdenProduccion, on_delete=models.CASCADE, related_name="registros")
    lote = models.ForeignKey(Lote, on_delete=models.SET_NULL, null=True, blank=True, related_name="registros")
    estacion = models.CharField(max_length=15, choices=Estacion.choices)
    etapa = models.CharField(max_length=80, help_text="Ej. 'Lavado', 'Secado controlado', 'Inoculación'")
    control = models.CharField(max_length=6, choices=ControlCalidad.choices, default=ControlCalidad.GENERAL)
    equipo = models.ForeignKey(Equipo, on_delete=models.SET_NULL, null=True, blank=True)
    variables = models.JSONField(default=dict, help_text="Variables medidas: {'ph': 3.9, 'temp_c': 24}")
    cantidad_entrada = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    cantidad_salida = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    merma = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    conforme = models.BooleanField(default=True)
    desviaciones = models.JSONField(default=list, blank=True)
    observaciones = models.TextField(blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registros_ebr")
    fecha = models.DateTimeField(default=timezone.now)
    firmado = models.BooleanField(default=False)
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="registros_aprobados"
    )
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["fecha"]
        verbose_name = "Registro de etapa (eBR)"
        verbose_name_plural = "Registros de etapa (eBR)"

    def __str__(self):
        return f"{self.orden.codigo} · {self.etapa} · {self.fecha:%Y-%m-%d %H:%M}"

    @property
    def estacion_responsable(self):
        return self.estacion

    def evaluar(self):
        """Compara las variables con la especificación del control y llena desviaciones/conforme."""
        spec = ESPECIFICACION_CONTROLES.get(self.control, {})
        desv = []
        for var, (lo, hi, unidad) in spec.items():
            if var not in self.variables or self.variables[var] in ("", None):
                desv.append(f"{var}: sin dato")
                continue
            v = Decimal(str(self.variables[var]))
            if lo is not None and v < Decimal(str(lo)):
                desv.append(f"{var} = {v}{unidad} < {lo}{unidad}")
            if hi is not None and v > Decimal(str(hi)):
                desv.append(f"{var} = {v}{unidad} > {hi}{unidad}")
        self.desviaciones = desv
        self.conforme = not desv
        return self.conforme

    def save(self, *args, **kwargs):
        if self.control in ESPECIFICACION_CONTROLES:
            self.evaluar()
        super().save(*args, **kwargs)


class CorteDestilacion(models.Model):
    """
    PCC-1: separación de cabezas / corazón / colas en el alambique.
    Los límites de metanol y ABV se parametrizan; verifíquelos contra la
    norma INEN vigente para aguardiente antes de producción.
    """

    LIMITE_METANOL_MG_100ML_AA = Decimal("100")   # mg/100 mL de alcohol anhidro (parametrizable)
    ABV_MIN_CORAZON = Decimal("55")
    ABV_MAX_CORAZON = Decimal("80")

    registro = models.OneToOneField(RegistroEtapa, on_delete=models.CASCADE, related_name="corte")
    alambique = models.ForeignKey(Equipo, on_delete=models.PROTECT, limit_choices_to={"tipo": "ALAMBIQUE"})
    volumen_carga_l = models.DecimalField("Volumen de vino/mosto cargado (L)", max_digits=10, decimal_places=2)
    abv_carga = models.DecimalField("ABV de la carga (%)", max_digits=5, decimal_places=2)
    cabezas_l = models.DecimalField(max_digits=10, decimal_places=2)
    abv_cabezas = models.DecimalField(max_digits=5, decimal_places=2)
    corazon_l = models.DecimalField(max_digits=10, decimal_places=2)
    abv_corazon = models.DecimalField(max_digits=5, decimal_places=2)
    colas_l = models.DecimalField(max_digits=10, decimal_places=2)
    abv_colas = models.DecimalField(max_digits=5, decimal_places=2)
    temp_vapor_corte_cabeza_c = models.DecimalField(max_digits=5, decimal_places=1)
    temp_vapor_corte_cola_c = models.DecimalField(max_digits=5, decimal_places=1)
    metanol_mg_100ml_aa = models.DecimalField(
        "Metanol en corazón (mg/100 mL a.a.)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    curva_termica = models.JSONField(default=list, blank=True, help_text="[[minuto, °C vapor, %ABV flujo], …]")
    conforme = models.BooleanField(default=False, editable=False)
    motivos_no_conformidad = models.JSONField(default=list, editable=False)

    class Meta:
        verbose_name = "Corte de destilación (PCC-1)"
        verbose_name_plural = "Cortes de destilación (PCC-1)"

    @staticmethod
    def _lap(litros, abv):
        return (litros or 0) * (abv or 0) / Decimal("100")

    @property
    def lap_carga(self):
        return self._lap(self.volumen_carga_l, self.abv_carga)

    @property
    def lap_corazon(self):
        return self._lap(self.corazon_l, self.abv_corazon)

    @property
    def lap_total_fracciones(self):
        return (self._lap(self.cabezas_l, self.abv_cabezas) + self.lap_corazon
                + self._lap(self.colas_l, self.abv_colas))

    def evaluar_pcc1(self):
        m = []
        if self.metanol_mg_100ml_aa is None:
            m.append("Falta análisis de metanol en corazón.")
        elif self.metanol_mg_100ml_aa > self.LIMITE_METANOL_MG_100ML_AA:
            m.append(f"Metanol {self.metanol_mg_100ml_aa} > {self.LIMITE_METANOL_MG_100ML_AA} mg/100 mL a.a.")
        if not (self.ABV_MIN_CORAZON <= self.abv_corazon <= self.ABV_MAX_CORAZON):
            m.append(f"ABV de corazón {self.abv_corazon}% fuera de {self.ABV_MIN_CORAZON}–{self.ABV_MAX_CORAZON}%.")
        if self.cabezas_l <= 0:
            m.append("No se registró separación de cabezas.")
        if self.lap_carga and self.lap_total_fracciones > self.lap_carga * Decimal("1.02"):
            m.append("Balance de alcohol incoherente: fracciones > carga.")
        self.motivos_no_conformidad = m
        self.conforme = not m
        return self.conforme

    def save(self, *args, **kwargs):
        self.evaluar_pcc1()
        super().save(*args, **kwargs)
        # Propaga el resultado al registro eBR y al lote
        reg = self.registro
        reg.conforme = self.conforme
        reg.desviaciones = self.motivos_no_conformidad
        RegistroEtapa.objects.filter(pk=reg.pk).update(conforme=self.conforme, desviaciones=self.motivos_no_conformidad)
        if reg.lote_id:
            Lote.objects.filter(pk=reg.lote_id).update(pcc1_conforme=self.conforme)


class LecturaIoT(models.Model):
    """Lectura continua desde ESP32 (MQTT → Node-RED → API, o bridge MQTT directo)."""

    class Variable(models.TextChoices):
        TEMP = "TEMP", "Temperatura (°C)"
        PH = "PH", "pH"
        BRIX = "BRIX", "Grados Brix"
        DENSIDAD = "DENS", "Densidad (g/mL)"
        ABV = "ABV", "% ABV en flujo"
        TEMP_VAPOR = "TVAP", "Temperatura de vapor (°C)"
        HUMEDAD = "HUM", "Humedad (%)"
        NIVEL = "NIVEL", "Nivel (L)"
        PRESION = "PRES", "Presión (bar)"

    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name="lecturas")
    orden = models.ForeignKey(OrdenProduccion, on_delete=models.SET_NULL, null=True, blank=True, related_name="lecturas")
    variable = models.CharField(max_length=6, choices=Variable.choices)
    valor = models.DecimalField(max_digits=10, decimal_places=4)
    dispositivo = models.CharField(max_length=40)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    recibido = models.DateTimeField(auto_now_add=True)
    fuera_de_rango = models.BooleanField(default=False)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["equipo", "variable", "-timestamp"])]
        verbose_name = "Lectura IoT"
        verbose_name_plural = "Lecturas IoT"

    def __str__(self):
        return f"{self.equipo.codigo} {self.variable}={self.valor} @ {self.timestamp:%H:%M:%S}"


# --------------------------------------------------------------- Existencias y Kardex
class Existencia(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, related_name="existencias")
    ubicacion = models.ForeignKey(UbicacionWMS, on_delete=models.PROTECT, related_name="existencias")
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lote", "ubicacion"], name="existencia_unica")]

    def __str__(self):
        return f"{self.lote} @ {self.ubicacion}: {self.cantidad}"


class MovimientoKardex(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada (recepción)"
        PRODUCCION = "PRODUCCION", "Ingreso por producción"
        CONSUMO = "CONSUMO", "Consumo en producción"
        TRANSFERENCIA = "TRANSF", "Transferencia interna"
        SALIDA = "SALIDA", "Salida / despacho"
        MERMA = "MERMA", "Merma"
        AJUSTE = "AJUSTE", "Ajuste de inventario"

    class MotivoMerma(models.TextChoices):
        PULPA = "PULPA", "Pulpa / fibra residual"
        CABEZAS = "CABEZAS", "Cabezas no aptas"
        COLAS = "COLAS", "Colas no aptas"
        EVAPORACION = "EVAP", "Evaporación"
        ROTURA = "ROTURA", "Rotura de envase"
        CADUCIDAD = "CADUC", "Caducidad"
        CALIDAD = "CALIDAD", "Rechazo de calidad"
        OTRO = "OTRO", "Otro"

    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name="movimientos")
    orden = models.ForeignKey(OrdenProduccion, on_delete=models.SET_NULL, null=True, blank=True, related_name="movimientos")
    despacho = models.ForeignKey("Despacho", on_delete=models.SET_NULL, null=True, blank=True, related_name="movimientos")
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, help_text="Siempre positiva; el tipo define el signo.")
    unidad = models.CharField(max_length=5)
    ubicacion_origen = models.ForeignKey(UbicacionWMS, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    ubicacion_destino = models.ForeignKey(UbicacionWMS, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    motivo_merma = models.CharField(max_length=8, choices=MotivoMerma.choices, blank=True)
    saldo_lote = models.DecimalField(max_digits=12, decimal_places=3, help_text="Saldo del lote tras el movimiento.")
    referencia = models.CharField(max_length=80, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    estacion = models.CharField(max_length=15, choices=Estacion.choices)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Movimiento de Kardex"
        verbose_name_plural = "Kardex"

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d} {self.tipo} {self.lote} {self.cantidad}"

    @property
    def estacion_responsable(self):
        return self.estacion

    @property
    def signo(self):
        if self.tipo in (self.Tipo.ENTRADA, self.Tipo.PRODUCCION):
            return 1
        if self.tipo == self.Tipo.TRANSFERENCIA:
            return 0
        if self.tipo == self.Tipo.AJUSTE:
            return 1 if self.ubicacion_destino_id else -1
        return -1


class ConteoCiclico(models.Model):
    """Base para el indicador IRA (Inventory Record Accuracy)."""

    TOLERANCIA_PCT = Decimal("2.0")

    fecha = models.DateTimeField(default=timezone.now)
    ubicacion = models.ForeignKey(UbicacionWMS, on_delete=models.PROTECT)
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT)
    cantidad_sistema = models.DecimalField(max_digits=12, decimal_places=3)
    cantidad_fisica = models.DecimalField(max_digits=12, decimal_places=3)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    ajustado = models.BooleanField(default=False)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Conteo cíclico"
        verbose_name_plural = "Conteos cíclicos"

    @property
    def diferencia(self):
        return self.cantidad_fisica - self.cantidad_sistema

    @property
    def exacto(self):
        if self.cantidad_sistema == 0:
            return self.cantidad_fisica == 0
        return abs(self.diferencia) / self.cantidad_sistema * 100 <= self.TOLERANCIA_PCT

    @classmethod
    def ira(cls, desde=None):
        qs = cls.objects.all()
        if desde:
            qs = qs.filter(fecha__gte=desde)
        total = qs.count()
        if not total:
            return None
        return round(sum(1 for c in qs if c.exacto) / total * 100, 2)


# =============================================================================
# 4. LOGÍSTICA · DESPACHO AL CEDI
# =============================================================================


class Despacho(models.Model):
    class Estado(models.TextChoices):
        PREPARACION = "PREP", "En preparación (picking)"
        LISTO = "LISTO", "Listo para carga"
        ENVIADO = "ENVIADO", "Enviado al CEDI"
        CONFIRMADO = "CONFIRMADO", "Recibido por CEDI"
        ERROR = "ERROR", "Error de sincronización"

    codigo = models.CharField(max_length=24, unique=True)
    cedi_destino = models.CharField(max_length=30)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PREPARACION)
    fecha_programada = models.DateTimeField()
    fecha_envio = models.DateTimeField(null=True, blank=True)
    transportista = models.CharField(max_length=120, blank=True)
    placa_vehiculo = models.CharField(max_length=12, blank=True)
    conductor = models.CharField(max_length=120, blank=True)
    temperatura_transporte = models.CharField(max_length=30, blank=True, default="Ambiente")
    guia_remision = models.CharField(max_length=30, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    payload_enviado = models.JSONField(null=True, blank=True)
    respuesta_cedi = models.JSONField(null=True, blank=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha_programada"]

    def __str__(self):
        return self.codigo

    @property
    def estacion_responsable(self):
        return Estacion.ALMACEN


class DetalleDespacho(models.Model):
    despacho = models.ForeignKey(Despacho, on_delete=models.CASCADE, related_name="detalles")
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT)
    ubicacion_origen = models.ForeignKey(UbicacionWMS, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=12, decimal_places=3)
    unidades_empaque = models.PositiveIntegerField(default=0, help_text="Sacos o botellas.")
    codigo_palet = models.CharField(max_length=30, blank=True, help_text="SSCC / código de palet o caja.")
    pickeado = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Detalle de despacho"


# =============================================================================
# 5. COMERCIO · TIENDA EN LÍNEA
# =============================================================================


class Pedido(models.Model):
    class Estado(models.TextChoices):
        CARRITO = "CARRITO", "Carrito"
        CONFIRMADO = "CONF", "Confirmado"
        PAGADO = "PAGADO", "Pagado"
        ENTREGADO = "ENTREG", "Entregado"
        CANCELADO = "CANCEL", "Cancelado"

    codigo = models.CharField(max_length=20, unique=True)
    cliente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nombre = models.CharField(max_length=120)
    email = models.EmailField()
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    declara_mayor_edad = models.BooleanField(default=False)
    estado = models.CharField(max_length=8, choices=Estado.choices, default=Estado.CONFIRMADO)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return self.codigo


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.cantidad * self.precio_unitario


# =============================================================================
# 6. AUDITORÍA
# =============================================================================


class RegistroAuditoria(models.Model):
    class Accion(models.TextChoices):
        CREAR = "CREAR", "Creación"
        EDITAR = "EDITAR", "Edición"
        ELIMINAR = "ELIMINAR", "Eliminación"
        LIBERAR = "LIBERAR", "Liberación de lote"
        RECHAZAR = "RECHAZAR", "Rechazo / retención"
        DENEGADO = "DENEGADO", "Intento denegado"
        LOGIN = "LOGIN", "Inicio de sesión"
        LOGOUT = "LOGOUT", "Cierre de sesión"
        LOGIN_FALLIDO = "LOGIN_KO", "Inicio de sesión fallido"
        EXPORTAR = "EXPORTAR", "Exportación de informe"
        API = "API", "Integración API"

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    username = models.CharField(max_length=150, blank=True, help_text="Se conserva aunque se borre el usuario.")
    rol = models.CharField(max_length=10, blank=True)
    estacion_usuario = models.CharField(max_length=15, blank=True)
    accion = models.CharField(max_length=10, choices=Accion.choices)
    modelo = models.CharField(max_length=60, blank=True)
    objeto_id = models.CharField(max_length=40, blank=True)
    objeto_repr = models.CharField(max_length=200, blank=True)
    estacion_objeto = models.CharField(max_length=15, blank=True)
    cambios = models.JSONField(default=dict, blank=True, help_text="{campo: [antes, después]}")
    sobrescritura_admin = models.BooleanField(
        default=False, help_text="Un administrador modificó un dato registrado por otro usuario/estación."
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    detalle = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Registro de auditoría"
        verbose_name_plural = "Bitácora de auditoría"
        indexes = [models.Index(fields=["usuario", "-timestamp"]), models.Index(fields=["modelo", "objeto_id"])]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.username} {self.accion} {self.objeto_repr}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("La bitácora de auditoría es de solo inserción.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("La bitácora de auditoría no se puede eliminar.")

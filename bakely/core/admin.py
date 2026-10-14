from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Categoria, ConteoCiclico, CorteDestilacion, Despacho, DetalleDespacho, DetallePedido, Equipo, Existencia,
    LecturaIoT, Lote, MovimientoKardex, OrdenProduccion, Pedido, PerfilUsuario, Producto, RegistroAuditoria,
    RegistroEtapa, UbicacionWMS, UnidadSerializada,
)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("miniatura", "codigo", "nombre", "categoria", "linea", "regla_rotacion", "precio_venta",
                    "publicado_tienda")
    list_filter = ("linea", "categoria", "publicado_tienda")
    search_fields = ("codigo", "nombre")

    @admin.display(description="Foto")
    def miniatura(self, obj):
        return format_html('<img src="{}" style="height:36px;border-radius:6px">', obj.imagen.url) if obj.imagen else "—"


class CorteInline(admin.StackedInline):
    model = CorteDestilacion
    extra = 0
    readonly_fields = ("conforme", "motivos_no_conformidad")


@admin.register(RegistroEtapa)
class RegistroEtapaAdmin(admin.ModelAdmin):
    list_display = ("orden", "etapa", "estacion", "control", "conforme", "registrado_por", "fecha")
    list_filter = ("estacion", "control", "conforme")
    inlines = [CorteInline]


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = ("codigo", "producto", "tipo", "estado", "fecha_elaboracion", "fecha_caducidad", "pcc1_conforme")
    list_filter = ("estado", "tipo", "producto__linea")
    search_fields = ("codigo",)
    filter_horizontal = ("lotes_origen",)
    readonly_fields = ("qr_token", "liberado_por", "fecha_liberacion")


@admin.register(RegistroAuditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "username", "rol", "accion", "modelo", "objeto_repr", "sobrescritura_admin", "ip")
    list_filter = ("accion", "rol", "sobrescritura_admin")
    search_fields = ("username", "objeto_repr", "detalle")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(MovimientoKardex)
class KardexAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tipo", "lote", "cantidad", "unidad", "saldo_lote", "usuario", "estacion")
    list_filter = ("tipo", "estacion")

    def has_change_permission(self, request, obj=None):
        return False


class DetalleDespachoInline(admin.TabularInline):
    model = DetalleDespacho
    extra = 0


@admin.register(Despacho)
class DespachoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "cedi_destino", "estado", "fecha_programada")
    inlines = [DetalleDespachoInline]


@admin.register(LecturaIoT)
class LecturaAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "equipo", "variable", "valor", "fuera_de_rango")
    list_filter = ("equipo", "variable", "fuera_de_rango")


for m in (PerfilUsuario, Categoria, UbicacionWMS, Equipo, OrdenProduccion, UnidadSerializada, Existencia,
          ConteoCiclico, Pedido, DetallePedido):
    admin.site.register(m)

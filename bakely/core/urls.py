from django.contrib.auth.views import LogoutView
from django.urls import path

from . import exports, views

app_name = "core"

urlpatterns = [
    # Módulo 0 · Landing
    path("", views.landing, name="landing"),
    path("contadores.json", views.contadores_json, name="contadores_json"),

    # Módulo 1 · Tienda y trazabilidad (público)
    path("tienda/", views.catalogo, name="catalogo"),
    path("tienda/producto/<str:codigo>/", views.producto_detalle, name="producto_detalle"),
    path("tienda/carrito/", views.carrito, name="carrito"),
    path("tienda/carrito/agregar/<str:codigo>/", views.carrito_agregar, name="carrito_agregar"),
    path("tienda/carrito/quitar/<str:codigo>/", views.carrito_quitar, name="carrito_quitar"),
    path("trazabilidad/", views.trazabilidad_buscar, name="trazabilidad"),
    path("trazabilidad/<uuid:token>/", views.trazabilidad_detalle, name="trazabilidad_detalle"),

    # Terminal de planta
    path("planta/login/", views.TerminalLoginView.as_view(), name="login"),
    path("planta/logout/", LogoutView.as_view(), name="logout"),
    path("planta/", views.planta_dashboard, name="planta_dashboard"),
    path("planta/estado.json", views.planta_estado_json, name="planta_estado_json"),

    # Módulo 2 · WMS
    path("planta/wms/", views.wms, name="wms"),
    path("planta/wms/movimiento/", views.wms_movimiento, name="wms_movimiento"),
    path("planta/wms/recepcion/", views.wms_recepcion, name="wms_recepcion"),
    path("planta/wms/picking/<str:codigo>/", views.picking_sugerido, name="picking_sugerido"),

    # Módulo 3 · MES / eBR
    path("planta/ordenes/", views.ordenes, name="ordenes"),
    path("planta/ordenes/<int:pk>/", views.orden_detalle, name="orden_detalle"),
    path("planta/ordenes/<int:pk>/registrar/", views.registrar_etapa, name="registrar_etapa"),
    path("planta/registros/<int:pk>/aprobar/", views.aprobar_registro, name="aprobar_registro"),
    path("planta/lotes/<str:codigo>/", views.lote_detalle, name="lote_detalle"),
    path("planta/lotes/<str:codigo>/liberacion/", views.lote_liberar, name="lote_liberar"),

    # Módulo 4 · Despacho CEDI
    path("planta/despachos/", views.despachos, name="despachos"),
    path("planta/despachos/<int:pk>/", views.despacho_detalle, name="despacho_detalle"),
    path("planta/despachos/<int:pk>/accion/", views.despacho_accion, name="despacho_accion"),

    # Módulo 5 · Reportes
    path("planta/reportes/", views.reportes, name="reportes"),
    path("planta/reportes/ebr/<str:codigo>.pdf", exports.exportar_ebr_pdf, name="exportar_ebr"),
    path("planta/reportes/auditoria.<str:ext>", exports.exportar_auditoria, name="exportar_auditoria"),
    path("planta/reportes/kardex.<str:ext>", exports.exportar_kardex, name="exportar_kardex"),
    path("planta/reportes/manifiesto/<int:pk>.<str:ext>", exports.exportar_manifiesto, name="exportar_manifiesto"),

    # Módulo 6 · Usuarios
    path("planta/usuarios/", views.usuarios, name="usuarios"),
    path("planta/usuarios/nuevo/", views.usuario_editar, name="usuario_nuevo"),
    path("planta/usuarios/<int:pk>/", views.usuario_editar, name="usuario_editar"),
    path("planta/usuarios/<int:pk>/estacion/", views.usuario_toggle_estacion, name="usuario_toggle_estacion"),
]

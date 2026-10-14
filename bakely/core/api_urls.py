from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from . import api_views as v

publico = DefaultRouter()
publico.register("catalogo", v.CatalogoPublicoViewSet, basename="catalogo")

planta = DefaultRouter()
planta.register("productos", v.ProductoViewSet)
planta.register("ubicaciones", v.UbicacionViewSet)
planta.register("existencias", v.ExistenciaViewSet, basename="existencia")
planta.register("kardex", v.KardexViewSet)
planta.register("equipos", v.EquipoViewSet)
planta.register("ordenes", v.OrdenProduccionViewSet)
planta.register("lotes", v.LoteViewSet)
planta.register("ebr", v.RegistroEtapaViewSet)
planta.register("unidades", v.UnidadSerializadaViewSet)
planta.register("auditoria", v.AuditoriaViewSet)

cedi = DefaultRouter()
cedi.register("despachos", v.DespachoViewSet)

urlpatterns = [
    path("token/", obtain_auth_token, name="api_token"),
    path("", include(publico.urls)),
    path("trazabilidad/<uuid:token>/", v.trazabilidad_publica, name="api_trazabilidad"),
    path("planta/", include(planta.urls)),
    path("iot/lecturas/", v.iot_lecturas, name="api_iot_lecturas"),
    path("cedi/", include(cedi.urls)),
    path("cedi/confirmacion/", v.cedi_confirmacion, name="api_cedi_confirmacion"),
]

from django.conf import settings

from .permissions import es_admin, es_personal_planta, estacion_de, mapa_permisos, rol_de


def bakely(request):
    user = request.user
    ctx = {"BAKELY": settings.BAKELY}
    if user.is_authenticated:
        ctx.update({
            "rol_usuario": rol_de(user),
            "es_admin": es_admin(user),
            "es_personal_planta": es_personal_planta(user),
            "mi_estacion": estacion_de(user),
            "permisos_estacion": mapa_permisos(user),
        })
    carrito = request.session.get("carrito", {}) if hasattr(request, "session") else {}
    ctx["carrito_items"] = sum(carrito.values()) if carrito else 0
    return ctx

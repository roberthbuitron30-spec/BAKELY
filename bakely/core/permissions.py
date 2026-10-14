"""
BAKELY · Matriz de seguridad RBAC

Regla de oro:
  · Cliente      → solo tienda, visor QR y sus pedidos. Nunca el terminal de planta.
  · Operario     → VE todo el terminal de planta, pero EDITA solo su estación asignada.
  · Administrador→ "God Mode": edita todo, libera lotes, gestiona usuarios. Sus
                   sobrescrituras quedan marcadas en la bitácora.

Este módulo ofrece la misma regla en tres sabores:
  1. Funciones puras (rol_de, puede_editar_estacion) — usadas por todo lo demás.
  2. Decoradores y mixins para vistas Django (HTML).
  3. Clases de permiso para Django REST Framework.
"""
from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from rest_framework import permissions

from .models import Estacion, Rol


# --------------------------------------------------------------------------- 1. Núcleo
def rol_de(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return Rol.ADMIN
    perfil = getattr(user, "perfil", None)
    return perfil.rol if perfil else Rol.CLIENTE


def es_admin(user):
    return rol_de(user) == Rol.ADMIN


def es_personal_planta(user):
    return rol_de(user) in (Rol.OPERARIO, Rol.ADMIN)


def estacion_de(user):
    perfil = getattr(user, "perfil", None)
    if perfil and perfil.rol == Rol.OPERARIO and perfil.estacion_activa:
        return perfil.estacion
    return None


def estacion_objeto(obj):
    """Estación dueña de un objeto (todos los modelos editables exponen estacion_responsable)."""
    return getattr(obj, "estacion_responsable", None)


def puede_editar_estacion(user, estacion):
    if es_admin(user):
        return True
    return bool(estacion) and estacion_de(user) == estacion


def puede_editar(user, obj):
    return puede_editar_estacion(user, estacion_objeto(obj))


def mapa_permisos(user):
    """Diccionario {ESTACION: bool} para pintar candados en las plantillas."""
    return {e.value: puede_editar_estacion(user, e.value) for e in Estacion}


def _registrar_denegado(request, detalle, estacion=""):
    from .services import auditar  # import diferido (evita ciclo)
    auditar(request.user, "DENEGADO", detalle=detalle, estacion_objeto=estacion)


# --------------------------------------------------------------------------- 2. Vistas HTML
def personal_planta_requerido(view):
    """Login + rol operario/admin. Los clientes son redirigidos a la tienda."""

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/planta/login/?next={request.path}")
        if not es_personal_planta(request.user):
            _registrar_denegado(request, f"Cliente intentó acceder a {request.path}")
            raise PermissionDenied("El terminal de planta es exclusivo del personal técnico.")
        return view(request, *args, **kwargs)

    return _wrapped


def admin_requerido(view):
    @wraps(view)
    @personal_planta_requerido
    def _wrapped(request, *args, **kwargs):
        if not es_admin(request.user):
            _registrar_denegado(request, f"Acceso de operario a zona admin: {request.path}")
            raise PermissionDenied("Solo el Administrador General puede acceder.")
        return view(request, *args, **kwargs)

    return _wrapped


def estacion_requerida(estacion):
    """Para vistas POST que escriben datos de una estación fija."""

    def deco(view):
        @wraps(view)
        @personal_planta_requerido
        def _wrapped(request, *args, **kwargs):
            if request.method not in ("GET", "HEAD", "OPTIONS") and not puede_editar_estacion(request.user, estacion):
                _registrar_denegado(request, f"Edición bloqueada en estación {estacion}", estacion)
                raise PermissionDenied(f"Su estación no le permite modificar datos de {estacion}.")
            return view(request, *args, **kwargs)

        return _wrapped

    return deco


class PersonalPlantaMixin(AccessMixin):
    login_url = "/planta/login/"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not es_personal_planta(request.user):
            raise PermissionDenied("El terminal de planta es exclusivo del personal técnico.")
        return super().dispatch(request, *args, **kwargs)


class AdminMixin(PersonalPlantaMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not es_admin(request.user):
            raise PermissionDenied("Solo el Administrador General puede acceder.")
        return super().dispatch(request, *args, **kwargs)


class EdicionPorEstacionMixin(PersonalPlantaMixin):
    """
    Para UpdateView / CreateView: GET siempre permitido (ver todo);
    POST solo si el usuario es dueño de la estación del objeto (o admin).
    Define `estacion_fija` o implementa `get_estacion()`.
    """

    estacion_fija = None

    def get_estacion(self):
        if self.estacion_fija:
            return self.estacion_fija
        obj = self.get_object() if hasattr(self, "get_object") else None
        return estacion_objeto(obj)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["puede_editar"] = puede_editar_estacion(self.request.user, self.get_estacion())
        ctx["estacion_bloqueo"] = self.get_estacion()
        return ctx

    def post(self, request, *args, **kwargs):
        estacion = self.get_estacion()
        if not puede_editar_estacion(request.user, estacion):
            _registrar_denegado(request, f"POST bloqueado en {request.path}", estacion)
            raise PermissionDenied("Solo lectura: esta estación no está asignada a su usuario.")
        return super().post(request, *args, **kwargs)


# --------------------------------------------------------------------------- 3. DRF
class EsPersonalPlanta(permissions.BasePermission):
    message = "Acceso exclusivo para personal de planta."

    def has_permission(self, request, view):
        return es_personal_planta(request.user)


class EsAdministrador(permissions.BasePermission):
    message = "Acceso exclusivo del Administrador General."

    def has_permission(self, request, view):
        return es_admin(request.user)


class LecturaTodosEdicionPorEstacion(permissions.BasePermission):
    """
    Operarios: lectura de todo; escritura solo de objetos de su estación.
    En creación, la vista debe implementar `estacion_para_creacion(request)`.
    """

    message = "Solo lectura: no puede modificar datos de otra estación."

    def has_permission(self, request, view):
        if not es_personal_planta(request.user):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if es_admin(request.user):
            return True
        if getattr(view, "action", None) == "create" or request.method == "POST":
            fn = getattr(view, "estacion_para_creacion", None)
            if fn is None:
                return False
            return puede_editar_estacion(request.user, fn(request))
        return True  # el chequeo fino se hace por objeto

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return puede_editar(request.user, obj)


class ClienteSoloLectura(permissions.BasePermission):
    """Catálogo público: GET para cualquiera, escritura solo admin."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return es_admin(request.user)

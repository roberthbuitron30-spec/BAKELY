"""Auditoría automática de sesiones y creación del perfil por defecto."""
from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PerfilUsuario, RegistroAuditoria, Rol


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def crear_perfil(sender, instance, created, **kwargs):
    if created and not hasattr(instance, "perfil"):
        PerfilUsuario.objects.create(usuario=instance, rol=Rol.ADMIN if instance.is_superuser else Rol.CLIENTE)


@receiver(user_logged_in)
def al_iniciar(sender, request, user, **kwargs):
    from .services import auditar
    auditar(user, "LOGIN", detalle=request.META.get("HTTP_USER_AGENT", "")[:200])


@receiver(user_logged_out)
def al_cerrar(sender, request, user, **kwargs):
    if user:
        from .services import auditar
        auditar(user, "LOGOUT")


@receiver(user_login_failed)
def al_fallar(sender, credentials, request=None, **kwargs):
    from .middleware import ip_actual
    RegistroAuditoria.objects.create(
        username=(credentials or {}).get("username", "")[:150], accion="LOGIN_KO", ip=ip_actual(),
        detalle="Credenciales inválidas en terminal de planta",
    )

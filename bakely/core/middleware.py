"""Guarda la request actual en un thread-local para que la auditoría conozca la IP."""
import threading

_local = threading.local()


def request_actual():
    return getattr(_local, "request", None)


def ip_actual():
    req = request_actual()
    if not req:
        return None
    fwd = req.META.get("HTTP_X_FORWARDED_FOR")
    return (fwd.split(",")[0].strip() if fwd else req.META.get("REMOTE_ADDR")) or None


class AuditoriaRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            return self.get_response(request)
        finally:
            _local.request = None

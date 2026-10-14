"""
BAKELY · Configuración Django
Planta de Almidones y Licores — UPEC (Universidad Politécnica Estatal del Carchi)

Las credenciales se leen de variables de entorno (archivo .env o del sistema).
Por defecto usa MySQL; para desarrollo rápido se puede usar SQLite con DB_ENGINE=sqlite.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key, default=None):
    return os.environ.get(key, default)


# Carga mínima de .env sin dependencias externas
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

SECRET_KEY = env("DJANGO_SECRET_KEY", "cambia-esta-clave-en-produccion-bakely-upec")
DEBUG = env("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "rest_framework.authtoken",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.AuditoriaRequestMiddleware",
]

ROOT_URLCONF = "bakely.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.bakely",
            ],
        },
    },
]

WSGI_APPLICATION = "bakely.wsgi.application"

# ---------------------------------------------------------------- Base de datos
if env("DB_ENGINE", "mysql") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "bakely.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME", "bakely_db"),
            "USER": env("DB_USER", "bakely"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "127.0.0.1"),
            "PORT": env("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "core:planta_dashboard"
LOGOUT_REDIRECT_URL = "core:landing"

# Sesiones del terminal de planta: expiran por inactividad (turnos)
SESSION_COOKIE_AGE = int(env("SESSION_COOKIE_AGE", 8 * 3600))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_CONTENT_TYPE_NOSNIFF = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_RATES": {"iot": "600/min", "anon": "60/min"},
}

# ---------------------------------------------------------------- Integraciones
BAKELY = {
    "PLANTA_CODIGO": env("PLANTA_CODIGO", "UPEC-PAL-01"),
    "PLANTA_NOMBRE": "Planta de Almidones y Licores UPEC",
    "INSTITUCION": "Universidad Politécnica Estatal del Carchi",
    "CEDI_CODIGO": env("CEDI_CODIGO", "CEDI-CARCHI-01"),
    "CEDI_API_URL": env("CEDI_API_URL", ""),
    "CEDI_API_TOKEN": env("CEDI_API_TOKEN", ""),
    # Token compartido para dispositivos ESP32 / Node-RED (cabecera X-Device-Key)
    "IOT_DEVICE_KEY": env("IOT_DEVICE_KEY", "cambia-esta-clave-iot"),
    "MQTT_HOST": env("MQTT_HOST", "localhost"),
    "MQTT_PORT": int(env("MQTT_PORT", 1883)),
    "MQTT_TOPIC": env("MQTT_TOPIC", "upec/bakely/+/+"),
    "ODOO_URL": env("ODOO_URL", ""),
    "ODOO_DB": env("ODOO_DB", ""),
    "ODOO_USER": env("ODOO_USER", ""),
    "ODOO_PASSWORD": env("ODOO_PASSWORD", ""),
}

"""
Django settings for the Child Wellness Platform.

Everything environment-specific lives here and nowhere else, so the same tree
runs unchanged in three places:

    local dev        -> DEBUG on, SQLite, insecure key fallback
    PythonAnywhere   -> DEBUG off, env secret, env allowed hosts
    tests / CI       -> DEBUG on, in-memory database

Required production environment variables:
    DJANGO_SECRET_KEY            long random string
    DJANGO_DEBUG                 "false"
    DJANGO_ALLOWED_HOSTS         "maaz2006.pythonanywhere.com"
    DJANGO_CSRF_TRUSTED_ORIGINS  "https://maaz2006.pythonanywhere.com"
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Local development convenience: a .env file next to manage.py is loaded if
# present. In production there is no .env — PythonAnywhere supplies the same
# names from the WSGI file.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover - dotenv is optional at runtime
    pass


# --------------------------------------------------------------------------
# Small helpers so settings stay readable
# --------------------------------------------------------------------------
def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-only-insecure-key-never-use-in-production-change-me",
)

DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,[::1],testserver",
)

CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "https://*.pythonanywhere.com",
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Project apps
    "core",
    "children",
    "domains",
    "analytics",
    "alerts",
    "feedback",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "core.context_processors.platform",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------
# Database
#
# SQLite is deliberate: single-school scale, zero operational surface, and it
# survives free-tier hosting constraints. Documented limitation for the report:
# write contention at high concurrency -> PostgreSQL would be the upgrade path.
# --------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL;",
        },
    }
}

# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:login"

# --------------------------------------------------------------------------
# Internationalisation
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static files
#
# No user file uploads anywhere in this project by design: avatars are emoji,
# report exports are print-to-PDF. That removes MEDIA_ROOT, Pillow and the
# whole class of "works locally, 404s in production" deployment failures.
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

if not DEBUG:
    # WhiteNoise serves pre-compressed assets from the WSGI process, so we do
    # not need nginx/Apache rewrites on the host.
    STORAGES["staticfiles"] = {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"
    }
    WHITENOISE_MAX_AGE = 60 * 60 * 24 * 30

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Platform behaviour (kept here so thresholds are configurable, not hardcoded)
# --------------------------------------------------------------------------
PLATFORM_NAME = "Kito"
PLATFORM_TAGLINE = "Child wellness, understood early."

# Minimum observations before a domain may be scored or alerted on. Below this
# the UI must say "not enough data yet" rather than inventing a score.
MIN_DOMAIN_DATAPOINTS = 3
MIN_ALERT_DATAPOINTS = 5

# --------------------------------------------------------------------------
# Security (production only)
# --------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

    # Deliberately NOT set, and both are visible as `manage.py check --deploy`
    # warnings (W004, W008):
    #
    #   SECURE_SSL_REDIRECT  - the host's proxy already forces HTTPS and
    #                          terminates TLS. Setting this behind a proxy that
    #                          is misread causes a redirect loop, which is a
    #                          worse failure than the warning it silences.
    #   SECURE_HSTS_SECONDS  - HSTS is effectively irreversible for its
    #                          duration and buys nothing on a host-provided
    #                          subdomain we do not control.
    #
    # Two remaining warnings, both understood and justified, is a better
    # position than a green tick achieved by copying settings we cannot reason
    # about. This paragraph belongs in the report's security section.

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO" if not DEBUG else "WARNING"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "wellness": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

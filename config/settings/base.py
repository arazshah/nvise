from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    MAX_PROVIDER_FILE_BYTES=(int, 20 * 1024 * 1024),
    MAX_WEBHOOK_BODY_BYTES=(int, 1024 * 1024),
    BALE_WEBHOOK_RATE_LIMIT_PER_MINUTE=(int, 120),
    STT_TIMEOUT_SECONDS=(float, 120.0),
    AI_EXTRACTION_TIMEOUT_SECONDS=(float, 120.0),
    REVIEW_LINK_TTL_MINUTES=(int, 15),
    CELERY_TASK_TIME_LIMIT=(int, 300),
    CELERY_TASK_SOFT_TIME_LIMIT=(int, 270),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="unsafe-dev-key")
NVISE_CONFIG_ENCRYPTION_KEY = env("NVISE_CONFIG_ENCRYPTION_KEY", default="")
DEBUG = env("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.accounts",
    "apps.tenants",
    "apps.cases",
    "apps.messaging",
    "apps.processing",
    "apps.transcription",
    "apps.evidence",
    "apps.intelligence",
    "apps.reports",
    "apps.documents",
    "apps.portal",
    "apps.subscriptions",
    "apps.audit",
    "apps.system",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.system.middleware.RequestContextMiddleware",
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3")}
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media")))
MAX_PROVIDER_FILE_BYTES = env.int("MAX_PROVIDER_FILE_BYTES", default=20 * 1024 * 1024)
MAX_WEBHOOK_BODY_BYTES = env.int("MAX_WEBHOOK_BODY_BYTES", default=1024 * 1024)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/review/login-required/"
WEB_BASE_URL = env("WEB_BASE_URL", default="http://localhost:8000").rstrip("/")
REVIEW_LINK_TTL_MINUTES = env.int("REVIEW_LINK_TTL_MINUTES", default=15)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TRACK_STARTED = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
CELERY_RESULT_EXPIRES = 86400
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=300)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=270)

BALE_BOT_TOKEN = env("BALE_BOT_TOKEN", default="")
BALE_BOT_ID = env("BALE_BOT_ID", default="primary")
BALE_WEBHOOK_SECRET = env("BALE_WEBHOOK_SECRET", default="")
BALE_WEBHOOK_RATE_LIMIT_PER_MINUTE = env.int("BALE_WEBHOOK_RATE_LIMIT_PER_MINUTE", default=120)

STT_PROVIDER = env("STT_PROVIDER", default="http")
STT_HTTP_ENDPOINT = env("STT_HTTP_ENDPOINT", default="")
STT_API_KEY = env("STT_API_KEY", default="")
STT_TIMEOUT_SECONDS = env.float("STT_TIMEOUT_SECONDS", default=120.0)

AI_EXTRACTION_PROVIDER = env("AI_EXTRACTION_PROVIDER", default="http")
AI_EXTRACTION_ENDPOINT = env("AI_EXTRACTION_ENDPOINT", default="")
AI_EXTRACTION_API_KEY = env("AI_EXTRACTION_API_KEY", default="")
AI_EXTRACTION_TIMEOUT_SECONDS = env.float("AI_EXTRACTION_TIMEOUT_SECONDS", default=120.0)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_context": {"()": "apps.system.logging.RequestContextFilter"}},
    "formatters": {"json": {"()": "apps.system.logging.JsonFormatter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_context"],
            "formatter": "json",
        }
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "nvise.request": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

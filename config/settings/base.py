from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    MAX_PROVIDER_FILE_BYTES=(int, 20 * 1024 * 1024),
    STT_TIMEOUT_SECONDS=(float, 120.0),
    AI_EXTRACTION_TIMEOUT_SECONDS=(float, 120.0),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="unsafe-dev-key")
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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media")))
MAX_PROVIDER_FILE_BYTES = env.int("MAX_PROVIDER_FILE_BYTES", default=20 * 1024 * 1024)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")

BALE_BOT_TOKEN = env("BALE_BOT_TOKEN", default="")
BALE_BOT_ID = env("BALE_BOT_ID", default="primary")
BALE_WEBHOOK_SECRET = env("BALE_WEBHOOK_SECRET", default="")

STT_PROVIDER = env("STT_PROVIDER", default="http")
STT_HTTP_ENDPOINT = env("STT_HTTP_ENDPOINT", default="")
STT_API_KEY = env("STT_API_KEY", default="")
STT_TIMEOUT_SECONDS = env.float("STT_TIMEOUT_SECONDS", default=120.0)

AI_EXTRACTION_PROVIDER = env("AI_EXTRACTION_PROVIDER", default="http")
AI_EXTRACTION_ENDPOINT = env("AI_EXTRACTION_ENDPOINT", default="")
AI_EXTRACTION_API_KEY = env("AI_EXTRACTION_API_KEY", default="")
AI_EXTRACTION_TIMEOUT_SECONDS = env.float("AI_EXTRACTION_TIMEOUT_SECONDS", default=120.0)

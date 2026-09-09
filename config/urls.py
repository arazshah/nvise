from django.contrib import admin
from django.urls import include, path

from apps.messaging.views import bale_webhook
from apps.system.views import health_live, health_ready

urlpatterns = [
    path("admin/", include("apps.system.urls")),
    path("admin/", admin.site.urls),
    path("health/", health_live, name="health"),
    path("health/live/", health_live, name="health-live"),
    path("health/ready/", health_ready, name="health-ready"),
    path("review/", include("apps.portal.urls")),
    path("webhooks/bale/<str:secret>/", bale_webhook, name="bale-webhook"),
]

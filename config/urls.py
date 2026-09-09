from django.contrib import admin
from django.urls import include, path

from apps.messaging.views import bale_webhook
from apps.system.views import favicon, guide, health, health_live, health_ready, home

urlpatterns = [
    path("", home, name="home"),
    path("guide/", guide, name="guide"),
    path("favicon.ico", favicon, name="favicon"),
    path("admin/", include("apps.system.urls")),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("health/live/", health_live, name="health-live"),
    path("health/ready/", health_ready, name="health-ready"),
    path("review/", include("apps.portal.urls")),
    path("webhooks/bale/<str:secret>/", bale_webhook, name="bale-webhook"),
]

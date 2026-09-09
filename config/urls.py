from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.messaging.views import bale_webhook


def health(_request):
    return JsonResponse({"status": "ok", "service": "nvise"})


urlpatterns = [
    path("admin/", include("apps.system.urls")),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("review/", include("apps.portal.urls")),
    path("webhooks/bale/<str:secret>/", bale_webhook, name="bale-webhook"),
]

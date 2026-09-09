from django.urls import path

from .views import saas_dashboard

app_name = "system"

urlpatterns = [
    path("saas/", saas_dashboard, name="saas-dashboard"),
]

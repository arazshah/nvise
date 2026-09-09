from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("login-required/", views.login_required_page, name="login-required"),
    path("access/<str:token>/", views.review_access, name="access"),
    path("cases/<str:case_code>/", views.case_review, name="case-review"),
    path("cases/<str:case_code>/edit/", views.edit_report, name="edit-report"),
    path("cases/<str:case_code>/approve/", views.approve_report_view, name="approve-report"),
    path(
        "cases/<str:case_code>/documents/<uuid:document_id>/download/",
        views.download_document,
        name="download-document",
    ),
]

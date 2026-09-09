from django.urls import path

from . import analysis_views, billing_views, views

app_name = "portal"

urlpatterns = [
    path("login-required/", views.login_required_page, name="login-required"),
    path("access/portal/<str:token>/", views.portal_access, name="portal-access"),
    path("access/<str:token>/", views.review_access, name="access"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("billing/", billing_views.billing_overview, name="billing"),
    path("billing/checkout/<slug:plan_code>/", billing_views.start_bale_checkout, name="billing-checkout"),
    path("cases/", views.case_list, name="case-list"),
    path("cases/<str:case_code>/", views.case_repository, name="case-repository"),
    path("cases/<str:case_code>/analysis/", analysis_views.analysis_overview, name="analysis-overview"),
    path("cases/<str:case_code>/analysis/start/", analysis_views.start_analysis_view, name="analysis-start"),
    path(
        "cases/<str:case_code>/analysis/continue/",
        analysis_views.continue_with_current_view,
        name="analysis-continue",
    ),
    path(
        "cases/<str:case_code>/analysis/report/",
        analysis_views.generate_report_view,
        name="analysis-generate-report",
    ),
    path("cases/<str:case_code>/review/", views.case_review, name="case-review"),
    path("cases/<str:case_code>/archive/", views.archive_case_view, name="archive-case"),
    path("cases/<str:case_code>/reopen/", views.reopen_case_view, name="reopen-case"),
    path(
        "cases/<str:case_code>/attachments/<uuid:attachment_id>/download/",
        views.download_attachment,
        name="download-attachment",
    ),
    path("cases/<str:case_code>/edit/", views.edit_report, name="edit-report"),
    path("cases/<str:case_code>/approve/", views.approve_report_view, name="approve-report"),
    path(
        "cases/<str:case_code>/documents/<uuid:document_id>/download/",
        views.download_document,
        name="download-document",
    ),
]

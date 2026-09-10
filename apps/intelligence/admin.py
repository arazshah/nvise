from django.contrib import admin

from .models import GoldenCase, GoldenCaseEvaluation


@admin.register(GoldenCase)
class GoldenCaseAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "name",
        "case",
        "is_active",
        "minimum_fact_recall",
        "maximum_redundant_question_rate",
        "minimum_expert_gap_recall",
        "minimum_grounding_ratio",
        "expert_report_score",
        "updated_at",
    )
    list_filter = ("is_active",)
    search_fields = ("key", "name", "case__case_code", "case__title")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Benchmark", {"fields": ("key", "name", "case", "is_active", "notes")}),
        (
            "Expected facts and questions",
            {
                "fields": (
                    "expected_facts",
                    "no_followup_fact_keys",
                    "expected_expert_judgment_fact_keys",
                ),
                "description": (
                    "expected_facts is human-verified ground truth. no_followup_fact_keys are facts that must not be asked again. "
                    "expected_expert_judgment_fact_keys are professional gaps the planner is expected to surface."
                ),
            },
        ),
        (
            "Quality gates",
            {
                "fields": (
                    "minimum_fact_recall",
                    "maximum_redundant_question_rate",
                    "minimum_expert_gap_recall",
                    "minimum_grounding_ratio",
                    "expert_report_score",
                )
            },
        ),
        ("Expert report rubric", {"fields": ("report_rubric",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(GoldenCaseEvaluation)
class GoldenCaseEvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "golden_case",
        "status",
        "overall_score",
        "fact_recall",
        "exact_fact_accuracy",
        "redundant_question_rate",
        "expert_gap_recall",
        "claim_grounding_ratio",
        "report_quality_score",
        "created_at",
    )
    list_filter = ("status", "golden_case")
    search_fields = ("golden_case__key", "golden_case__name", "git_sha", "model_name")
    readonly_fields = (
        "golden_case",
        "extraction_run",
        "report_revision_id",
        "status",
        "fact_recall",
        "exact_fact_accuracy",
        "redundant_question_rate",
        "expert_gap_recall",
        "claim_grounding_ratio",
        "report_quality_score",
        "overall_score",
        "metrics",
        "git_sha",
        "model_name",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

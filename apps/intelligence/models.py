import uuid

from django.db import models

from apps.cases.models import Case
from apps.evidence.models import Evidence


class Vertical(models.Model):
    key = models.SlugField(max_length=64, primary_key=True)
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)


class SubVertical(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vertical = models.ForeignKey(Vertical, on_delete=models.CASCADE, related_name="sub_verticals")
    key = models.SlugField(max_length=64)
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["vertical", "key"], name="uniq_vertical_subvertical_key")]


class FieldSchema(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sub_vertical = models.ForeignKey(SubVertical, on_delete=models.CASCADE, related_name="schemas")
    name = models.CharField(max_length=128)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["sub_vertical", "version"], name="uniq_subvertical_schema_version")]


class FieldDefinition(models.Model):
    class ValueType(models.TextChoices):
        TEXT = "text", "Text"
        INTEGER = "integer", "Integer"
        DECIMAL = "decimal", "Decimal"
        BOOLEAN = "boolean", "Boolean"
        DATE = "date", "Date"
        DATETIME = "datetime", "Datetime"
        CHOICE = "choice", "Choice"
        JSON = "json", "JSON"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema = models.ForeignKey(FieldSchema, on_delete=models.CASCADE, related_name="fields")
    key = models.SlugField(max_length=96)
    label = models.CharField(max_length=160)
    value_type = models.CharField(max_length=16, choices=ValueType.choices, default=ValueType.TEXT)
    required = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    choices = models.JSONField(default=list, blank=True)
    extraction_hints = models.JSONField(default=dict, blank=True)
    sequence = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sequence", "key"]
        constraints = [models.UniqueConstraint(fields=["schema", "key"], name="uniq_schema_field_key")]


class ExtractionRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="extraction_runs")
    schema = models.ForeignKey(FieldSchema, on_delete=models.PROTECT, related_name="extraction_runs")
    provider = models.CharField(max_length=64)
    model_name = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    input_snapshot = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class ExtractedFact(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        CONFIRMED = "confirmed", "Confirmed"
        CONFLICTED = "conflicted", "Conflicted"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="facts")
    field = models.ForeignKey(FieldDefinition, on_delete=models.PROTECT, related_name="facts")
    extraction_run = models.ForeignKey(ExtractionRun, on_delete=models.CASCADE, related_name="facts")
    value = models.JSONField()
    normalized_value = models.JSONField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)


class FactEvidence(models.Model):
    fact = models.ForeignKey(ExtractedFact, on_delete=models.CASCADE, related_name="evidence_links")
    evidence = models.ForeignKey(Evidence, on_delete=models.CASCADE, related_name="fact_links")
    relevance = models.FloatField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["fact", "evidence"], name="uniq_fact_evidence")]


class CaseFieldIssue(models.Model):
    class IssueType(models.TextChoices):
        MISSING = "missing", "Missing"
        CONFLICT = "conflict", "Conflict"
        INVALID = "invalid", "Invalid"
        EXPERT_JUDGMENT = "expert_judgment", "Expert judgment"

    class Status(models.TextChoices):
        OPEN = "open", "باز"
        RESOLVED = "resolved", "رفع شده"
        UNAVAILABLE = "unavailable", "اطلاعات در دسترس نیست"
        WAIVED = "waived", "با اطلاعات فعلی ادامه داده شود"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="field_issues")
    field = models.ForeignKey(FieldDefinition, on_delete=models.PROTECT, related_name="issues")
    issue_type = models.CharField(max_length=32, choices=IssueType.choices, db_index=True)
    details = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["case", "field", "issue_type"],
                condition=models.Q(status="open"),
                name="uniq_open_case_field_issue",
            )
        ]


class FollowUpQuestion(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ASKED = "asked", "Asked"
        ANSWERED = "answered", "Answered"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="follow_up_questions")
    issue = models.OneToOneField(
        CaseFieldIssue,
        on_delete=models.CASCADE,
        related_name="follow_up_question",
    )
    question_text = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    answer_evidence = models.ForeignKey(
        Evidence,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="answered_followups",
    )
    asked_at = models.DateTimeField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class GoldenCase(models.Model):
    """Human-curated benchmark definition for a real, anonymised case."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=96, unique=True)
    name = models.CharField(max_length=180)
    case = models.OneToOneField(Case, on_delete=models.CASCADE, related_name="golden_case")
    is_active = models.BooleanField(default=True, db_index=True)
    expected_facts = models.JSONField(default=dict, blank=True)
    no_followup_fact_keys = models.JSONField(default=list, blank=True)
    minimum_grounding_ratio = models.FloatField(default=0.90)
    minimum_fact_recall = models.FloatField(default=0.90)
    maximum_redundant_question_rate = models.FloatField(default=0.05)
    expert_report_score = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class GoldenCaseEvaluation(models.Model):
    class Status(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    golden_case = models.ForeignKey(GoldenCase, on_delete=models.CASCADE, related_name="evaluations")
    extraction_run = models.ForeignKey(
        ExtractionRun,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="golden_evaluations",
    )
    report_revision_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    fact_recall = models.FloatField(default=0)
    exact_fact_accuracy = models.FloatField(default=0)
    redundant_question_rate = models.FloatField(default=0)
    claim_grounding_ratio = models.FloatField(default=0)
    report_quality_score = models.FloatField(null=True, blank=True)
    overall_score = models.FloatField(default=0)
    metrics = models.JSONField(default=dict, blank=True)
    git_sha = models.CharField(max_length=64, blank=True)
    model_name = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.golden_case.key}: {self.status} ({self.overall_score:.3f})"

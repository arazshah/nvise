from django.core.management.base import BaseCommand, CommandError

from apps.cases.models import Case
from apps.intelligence.evaluation import evaluate_golden_case
from apps.intelligence.golden_presets import (
    INSURANCE_EXPECTED_EXPERT_GAP_KEYS,
    INSURANCE_GOLDEN_KEY,
    INSURANCE_GOLDEN_NOTES,
    INSURANCE_NO_FOLLOWUP_FACT_KEYS,
    INSURANCE_REPORT_RUBRIC,
)
from apps.intelligence.models import GoldenCase
from apps.reports.models import ExpertFactDecision


class Command(BaseCommand):
    help = "Bind a real insurance-loss case to Golden Case #1 using only expert-reviewed facts as ground truth."

    def add_arguments(self, parser):
        parser.add_argument("--case-code", required=True, help="Case code of the anonymised expert-reviewed insurance case.")
        parser.add_argument("--expert-score", type=float, default=None, help="Optional expert report quality score from 1 to 5.")
        parser.add_argument("--evaluate", action="store_true", help="Run the benchmark immediately after configuration.")

    def handle(self, *args, **options):
        try:
            case = Case.objects.select_related("created_by").get(case_code=options["case_code"])
        except Case.DoesNotExist as exc:
            raise CommandError("Case not found.") from exc

        if case.vertical_key and case.vertical_key != "insurance":
            raise CommandError("Golden Case #1 must be an insurance case.")

        decisions = list(
            ExpertFactDecision.objects.filter(case=case)
            .exclude(decision=ExpertFactDecision.Decision.REJECTED)
            .select_related("field", "source_fact")
            .order_by("field__sequence", "updated_at")
        )
        if not decisions:
            raise CommandError(
                "No expert-reviewed facts found. Review and confirm/correct the case facts in the grounding screen first."
            )

        expected_facts = {}
        for decision in decisions:
            if decision.decision == ExpertFactDecision.Decision.CORRECTED:
                value = decision.corrected_value
            else:
                source = decision.source_fact
                value = source.normalized_value if source.normalized_value is not None else source.value
            expected_facts[decision.field.key] = value

        protected = [key for key in INSURANCE_NO_FOLLOWUP_FACT_KEYS if key in expected_facts]
        schema_keys = set(
            case.extraction_runs.order_by("-created_at")
            .values_list("schema__fields__key", flat=True)
            .distinct()
        )
        expected_gaps = [key for key in INSURANCE_EXPECTED_EXPERT_GAP_KEYS if key in schema_keys]

        existing_for_case = GoldenCase.objects.filter(case=case).exclude(key=INSURANCE_GOLDEN_KEY).first()
        if existing_for_case:
            raise CommandError(f"Case is already attached to another Golden Case: {existing_for_case.key}")

        defaults = {
            "name": "Golden Case #1 — Insurance Loss Adjuster",
            "case": case,
            "is_active": True,
            "expected_facts": expected_facts,
            "no_followup_fact_keys": protected,
            "expected_expert_judgment_fact_keys": expected_gaps,
            "report_rubric": INSURANCE_REPORT_RUBRIC,
            "minimum_fact_recall": 0.95,
            "maximum_redundant_question_rate": 0.05,
            "minimum_expert_gap_recall": 0.80,
            "minimum_grounding_ratio": 0.95,
            "expert_report_score": options.get("expert_score"),
            "notes": INSURANCE_GOLDEN_NOTES,
        }
        golden, created = GoldenCase.objects.update_or_create(key=INSURANCE_GOLDEN_KEY, defaults=defaults)

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} {golden.key} from {len(expected_facts)} expert-reviewed fact(s)."))
        self.stdout.write(f"Protected no-followup facts: {', '.join(protected) or '-'}")
        self.stdout.write(f"Expected expert-gap facts: {', '.join(expected_gaps) or '-'}")

        if options.get("evaluate"):
            evaluation = evaluate_golden_case(golden)
            self.stdout.write(
                f"Evaluation: {evaluation.status} | overall={evaluation.overall_score:.3f} "
                f"fact_recall={evaluation.fact_recall:.3f} "
                f"redundant_questions={evaluation.redundant_question_rate:.3f} "
                f"expert_gap_recall={evaluation.expert_gap_recall:.3f} "
                f"grounding={evaluation.claim_grounding_ratio:.3f}"
            )

from django.core.management.base import BaseCommand, CommandError

from apps.intelligence.evaluation import evaluate_active_golden_cases


class Command(BaseCommand):
    help = "Evaluate all active Golden Cases and optionally fail when a quality gate is missed."

    def add_arguments(self, parser):
        parser.add_argument("--gate", action="store_true", help="Exit with failure if any Golden Case misses its thresholds.")
        parser.add_argument("--git-sha", default="", help="Commit SHA to attach to evaluation snapshots.")

    def handle(self, *args, **options):
        evaluations = evaluate_active_golden_cases(git_sha=options.get("git_sha") or None)
        if not evaluations:
            self.stdout.write(self.style.WARNING("No active Golden Cases configured."))
            return

        failed = []
        for item in evaluations:
            self.stdout.write(
                f"{item.golden_case.key}: {item.status} | overall={item.overall_score:.3f} "
                f"fact_recall={item.fact_recall:.3f} accuracy={item.exact_fact_accuracy:.3f} "
                f"redundant_questions={item.redundant_question_rate:.3f} grounding={item.claim_grounding_ratio:.3f}"
            )
            if item.status == item.Status.FAILED:
                failed.append(item)

        if failed and options.get("gate"):
            keys = ", ".join(item.golden_case.key for item in failed)
            raise CommandError(f"Golden Case quality gate failed: {keys}")

        self.stdout.write(self.style.SUCCESS(f"Evaluated {len(evaluations)} Golden Case(s)."))

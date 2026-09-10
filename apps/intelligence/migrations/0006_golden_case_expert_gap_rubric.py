from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("intelligence", "0005_golden_case_evaluation")]

    operations = [
        migrations.AddField(
            model_name="goldencase",
            name="expected_expert_judgment_fact_keys",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="goldencase",
            name="report_rubric",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="goldencase",
            name="minimum_expert_gap_recall",
            field=models.FloatField(default=0.8),
        ),
        migrations.AddField(
            model_name="goldencaseevaluation",
            name="expert_gap_recall",
            field=models.FloatField(default=1.0),
        ),
    ]

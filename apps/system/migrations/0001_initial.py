import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="TaskFailure",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("task_id", models.CharField(max_length=64, unique=True)),
                ("task_name", models.CharField(db_index=True, max_length=255)),
                ("exception_class", models.CharField(blank=True, max_length=255)),
                ("exception_message", models.TextField(blank=True)),
                ("traceback", models.TextField(blank=True)),
                ("retries", models.PositiveIntegerField(default=0)),
                ("resolved", models.BooleanField(db_index=True, default=False)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created_at"]},
        )
    ]

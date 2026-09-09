from django.db import migrations


def seed(apps, schema_editor):
    IntegrationSettings = apps.get_model("system", "IntegrationSettings")
    IntegrationSettings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("system", "0002_integrationsettings")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

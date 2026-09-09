from django.db import transaction

from .models import FieldDefinition, FieldSchema, SubVertical, Vertical


FIRE_LOSS_FIELDS = [
    ("policy_number", "شماره بیمه‌نامه", FieldDefinition.ValueType.TEXT, False),
    ("insured_name", "نام بیمه‌گذار", FieldDefinition.ValueType.TEXT, True),
    ("incident_datetime", "تاریخ و زمان حادثه", FieldDefinition.ValueType.DATETIME, True),
    ("incident_address", "نشانی محل حادثه", FieldDefinition.ValueType.TEXT, True),
    ("incident_cause", "علت یا منشأ حریق", FieldDefinition.ValueType.TEXT, True),
    ("property_type", "نوع مورد بیمه", FieldDefinition.ValueType.TEXT, True),
    ("damage_description", "شرح خسارت", FieldDefinition.ValueType.TEXT, True),
    ("estimated_damage_amount", "برآورد مبلغ خسارت", FieldDefinition.ValueType.DECIMAL, True),
    ("currency", "واحد پول", FieldDefinition.ValueType.CHOICE, True),
    ("fire_department_attended", "حضور آتش‌نشانی", FieldDefinition.ValueType.BOOLEAN, False),
    ("police_report_available", "وجود گزارش انتظامی", FieldDefinition.ValueType.BOOLEAN, False),
    ("injuries_or_fatalities", "مصدوم یا فوتی", FieldDefinition.ValueType.TEXT, False),
    ("salvage_condition", "وضعیت ضایعات و بازیافتی", FieldDefinition.ValueType.TEXT, False),
]


@transaction.atomic
def ensure_fire_loss_schema() -> FieldSchema:
    vertical, _ = Vertical.objects.get_or_create(key="insurance", defaults={"name": "Insurance"})
    sub_vertical, _ = SubVertical.objects.get_or_create(
        vertical=vertical,
        key="fire_loss",
        defaults={"name": "Fire loss adjustment"},
    )
    schema, _ = FieldSchema.objects.get_or_create(
        sub_vertical=sub_vertical,
        version=1,
        defaults={"name": "Insurance fire loss MVP"},
    )
    for sequence, (key, label, value_type, required) in enumerate(FIRE_LOSS_FIELDS):
        defaults = {
            "label": label,
            "value_type": value_type,
            "required": required,
            "sequence": sequence,
        }
        if key == "currency":
            defaults["choices"] = ["IRR", "IRT", "USD", "EUR", "OTHER"]
        FieldDefinition.objects.update_or_create(schema=schema, key=key, defaults=defaults)
    return schema

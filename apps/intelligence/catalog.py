from django.db import transaction

from .models import FieldDefinition, FieldSchema, SubVertical, Vertical


FIRE_LOSS_FIELDS = [
    ("policy_number", "شماره بیمه‌نامه", FieldDefinition.ValueType.TEXT, False),
    ("insured_name", "نام بیمه‌گذار", FieldDefinition.ValueType.TEXT, True),
    ("incident_datetime", "تاریخ و زمان حادثه", FieldDefinition.ValueType.DATETIME, True),
    ("incident_address", "نشانی محل حادثه", FieldDefinition.ValueType.TEXT, True),
    ("incident_cause", "علت یا منشأ حادثه", FieldDefinition.ValueType.TEXT, True),
    ("property_type", "نوع مورد بیمه", FieldDefinition.ValueType.TEXT, True),
    ("damage_description", "شرح خسارت", FieldDefinition.ValueType.TEXT, True),
    ("estimated_damage_amount", "برآورد مبلغ خسارت", FieldDefinition.ValueType.DECIMAL, True),
    ("currency", "واحد پول", FieldDefinition.ValueType.CHOICE, True),
    ("fire_department_attended", "حضور آتش‌نشانی", FieldDefinition.ValueType.BOOLEAN, False),
    ("police_report_available", "وجود گزارش انتظامی", FieldDefinition.ValueType.BOOLEAN, False),
    ("injuries_or_fatalities", "مصدوم یا فوتی", FieldDefinition.ValueType.TEXT, False),
    ("salvage_condition", "وضعیت ضایعات و بازیافتی", FieldDefinition.ValueType.TEXT, False),
]

LEGAL_FIELDS = [
    ("parties", "طرفین پرونده", FieldDefinition.ValueType.TEXT, True),
    ("case_subject", "موضوع و خواسته پرونده", FieldDefinition.ValueType.TEXT, True),
    ("chronology", "خط زمانی وقایع", FieldDefinition.ValueType.TEXT, True),
    ("claims", "ادعاها و خواسته‌ها", FieldDefinition.ValueType.TEXT, True),
    ("defenses", "دفاعیات و پاسخ‌ها", FieldDefinition.ValueType.TEXT, False),
    ("key_documents", "اسناد و ادله کلیدی", FieldDefinition.ValueType.TEXT, True),
    ("obligations", "تعهدات مرتبط", FieldDefinition.ValueType.TEXT, False),
    ("breach_or_event", "واقعه یا نقض مورد ادعا", FieldDefinition.ValueType.TEXT, False),
    ("legal_issues", "مسائل حقوقی قابل بررسی", FieldDefinition.ValueType.TEXT, False),
]

TECHNICAL_FIELDS = [
    ("subject", "موضوع بررسی فنی", FieldDefinition.ValueType.TEXT, True),
    ("technical_context", "زمینه و مشخصات فنی", FieldDefinition.ValueType.TEXT, True),
    ("observations", "مشاهدات و شواهد", FieldDefinition.ValueType.TEXT, True),
    ("failure_description", "شرح خرابی یا نقص", FieldDefinition.ValueType.TEXT, True),
    ("failure_mechanism", "مکانیزم خرابی", FieldDefinition.ValueType.TEXT, False),
    ("root_cause", "علت ریشه‌ای", FieldDefinition.ValueType.TEXT, False),
    ("contributing_factors", "عوامل مؤثر", FieldDefinition.ValueType.TEXT, False),
    ("impact_extent", "دامنه اثر یا خسارت", FieldDefinition.ValueType.TEXT, False),
    ("remediation", "اقدامات اصلاحی", FieldDefinition.ValueType.TEXT, False),
]


@transaction.atomic
def _ensure_schema(*, vertical_key: str, vertical_name: str, sub_vertical_key: str, sub_vertical_name: str, schema_name: str, fields):
    vertical, _ = Vertical.objects.get_or_create(key=vertical_key, defaults={"name": vertical_name})
    sub_vertical, _ = SubVertical.objects.get_or_create(
        vertical=vertical,
        key=sub_vertical_key,
        defaults={"name": sub_vertical_name},
    )
    schema, _ = FieldSchema.objects.get_or_create(
        sub_vertical=sub_vertical,
        version=1,
        defaults={"name": schema_name},
    )
    for sequence, (key, label, value_type, required) in enumerate(fields):
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


@transaction.atomic
def ensure_fire_loss_schema() -> FieldSchema:
    return _ensure_schema(
        vertical_key="insurance",
        vertical_name="Insurance",
        sub_vertical_key="fire_loss",
        sub_vertical_name="Fire loss adjustment",
        schema_name="Insurance fire loss MVP",
        fields=FIRE_LOSS_FIELDS,
    )


def ensure_schema_for_case(case) -> FieldSchema:
    vertical = case.vertical_key or ""
    sub_vertical = case.sub_vertical_key or ""
    if vertical == "legal":
        return _ensure_schema(
            vertical_key="legal",
            vertical_name="Legal",
            sub_vertical_key=sub_vertical or "general_legal",
            sub_vertical_name=sub_vertical or "General legal case",
            schema_name=f"Legal case schema - {sub_vertical or 'general'}",
            fields=LEGAL_FIELDS,
        )
    if vertical == "technical":
        return _ensure_schema(
            vertical_key="technical",
            vertical_name="Technical",
            sub_vertical_key=sub_vertical or "general_review",
            sub_vertical_name=sub_vertical or "General technical review",
            schema_name=f"Technical case schema - {sub_vertical or 'general'}",
            fields=TECHNICAL_FIELDS,
        )
    if vertical == "insurance" and sub_vertical and sub_vertical != "fire_loss":
        return _ensure_schema(
            vertical_key="insurance",
            vertical_name="Insurance",
            sub_vertical_key=sub_vertical,
            sub_vertical_name=sub_vertical.replace("_", " ").title(),
            schema_name=f"Insurance loss schema - {sub_vertical}",
            fields=FIRE_LOSS_FIELDS,
        )
    return ensure_fire_loss_schema()

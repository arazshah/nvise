INSURANCE_GOLDEN_KEY = "insurance-loss-adjuster-001"

INSURANCE_NO_FOLLOWUP_FACT_KEYS = [
    "policy_number",
    "insured_name",
    "incident_datetime",
    "incident_address",
    "property_type",
    "damage_description",
]

INSURANCE_EXPECTED_EXPERT_GAP_KEYS = [
    "incident_cause",
    "estimated_damage_amount",
]

INSURANCE_REPORT_RUBRIC = {
    "scale": "1-5",
    "minimum_recommended_score": 4.0,
    "criteria": [
        {
            "key": "document_use",
            "label": "استفاده واقعی از بیمه‌نامه، تصاویر، اظهارات و سایر مدارک",
            "weight": 20,
        },
        {
            "key": "technical_reasoning",
            "label": "تفکیک واقعیت، علت‌یابی فنی و نظر کارشناسی",
            "weight": 20,
        },
        {
            "key": "coverage_reasoning",
            "label": "تحلیل محتاطانه پوشش، شرایط، استثنائات و فرانشیز بدون ادعای بی‌منبع",
            "weight": 20,
        },
        {
            "key": "damage_quantum",
            "label": "تفکیک اقلام خسارت و کفایت مبنای برآورد مالی",
            "weight": 15,
        },
        {
            "key": "grounding",
            "label": "قابلیت ردیابی ادعاهای مادی تا Evidence",
            "weight": 15,
        },
        {
            "key": "professional_usability",
            "label": "قابل استفاده بودن گزارش برای کارشناس خسارت و پرونده شرکت بیمه",
            "weight": 10,
        },
    ],
    "hard_failures": [
        "پرسیدن دوباره Fact واضحی که در مدارک موجود است",
        "ساختن شماره، تاریخ، مبلغ، پوشش یا استثناء بدون Evidence",
        "نتیجه قطعی پوشش بیمه‌ای بدون مستندات کافی",
        "نادیده گرفتن تعارض واقعی بین مدارک و اظهارات",
    ],
}

INSURANCE_GOLDEN_NOTES = """Golden Case #1 — Insurance Loss Adjuster
هدف: جلوگیری از تکرار بازخورد کارشناس که اطلاعات واضح بیمه‌نامه/مدارک دوباره از او پرسیده شد.
Ground truth فقط از Factهای تأیید یا اصلاح‌شده توسط کارشناس ساخته می‌شود.
سؤال‌های ساده درباره facts موجود باید حذف شوند؛ در مقابل decision gapهای علت/کفایت برآورد باید حفظ شوند.
گزارش باید حرفه‌ای، evidence-grounded و مناسب استفاده کارشناس خسارت باشد.
"""

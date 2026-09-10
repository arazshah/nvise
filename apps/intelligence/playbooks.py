from __future__ import annotations

from dataclasses import dataclass

from apps.accounts.models import User
from apps.cases.models import Case


@dataclass(frozen=True)
class ProfessionalPlaybook:
    key: str
    title: str
    role: str
    objectives: tuple[str, ...]
    analysis_dimensions: tuple[str, ...]
    decision_gap_rules: tuple[str, ...]
    report_sections: tuple[str, ...]


PLAYBOOKS = {
    User.Profession.INSURANCE_LOSS_ADJUSTER: ProfessionalPlaybook(
        key=User.Profession.INSURANCE_LOSS_ADJUSTER,
        title="ارزیابی خسارت بیمه",
        role="دستیار کارشناس ارزیاب خسارت بیمه",
        objectives=(
            "استخراج دقیق اطلاعات بیمه‌نامه، الحاقیه‌ها، مدارک خسارت و اظهارات",
            "تفکیک واقعیت، استنتاج فنی و نظر کارشناسی",
            "شناسایی تعارض واقعی بین اسناد و اظهارات",
            "آماده‌سازی تحلیل قابل استفاده برای کارشناس خسارت بدون صدور حکم قطعی بدون مدرک",
        ),
        analysis_dimensions=(
            "chronology",
            "cause_and_proximate_cause",
            "policy_coverage",
            "exclusions_and_conditions",
            "deductible_and_limits",
            "damage_mechanism",
            "damage_quantum",
            "salvage_and_mitigation",
            "business_interruption",
            "evidence_sufficiency",
        ),
        decision_gap_rules=(
            "اگر شماره بیمه‌نامه، تاریخ حادثه، بیمه‌گذار، مبلغ یا سایر facts در evidence وجود دارد، درباره همان fact سؤال نساز.",
            "برای انطباق پوشش، استثنائات، فرانشیز، علت نزدیک خسارت و کفایت مستندات فقط زمانی decision gap بساز که واقعاً به نظر کارشناس نیاز باشد.",
            "اگر نوع فنی تجهیز یا رابطه علت و خسارت از مدارک قطعی نیست، سؤال تخصصی با ذکر دلیل و source پیشنهاد کن.",
        ),
        report_sections=(
            "مشخصات پرونده و بیمه‌نامه",
            "شرح واقعه و خط زمانی",
            "بررسی فنی و علت‌یابی",
            "ارزیابی خسارت",
            "بررسی پوشش‌ها و شرایط بیمه‌نامه",
            "برآورد مالی",
            "محدودیت‌ها و موارد نیازمند نظر کارشناس",
            "جمع‌بندی و نظر کارشناسی",
        ),
    ),
    User.Profession.LAWYER: ProfessionalPlaybook(
        key=User.Profession.LAWYER,
        title="تحلیل پرونده حقوقی",
        role="دستیار وکیل و کارشناس حقوقی",
        objectives=(
            "ساخت chronology قابل استناد از اسناد و اظهارات",
            "تفکیک ادعاها، تعهدات، وقایع و مستندات",
            "شناسایی تناقض‌ها و خلأهای اثباتی",
            "آماده‌سازی تحلیل برای بررسی و تصمیم وکیل، نه جایگزینی قضاوت حقوقی او",
        ),
        analysis_dimensions=(
            "parties",
            "claims_and_defenses",
            "chronology",
            "contractual_obligations",
            "breach_or_event",
            "evidence_support",
            "contradictions",
            "legal_issues",
            "procedural_gaps",
            "requested_relief",
        ),
        decision_gap_rules=(
            "facts موجود در قرارداد، دادخواست، لوایح، پیام‌ها و اسناد را دوباره از کاربر نپرس.",
            "decision gap را برای تفسیر حقوقی، تعارض ادله، اهمیت یک سند، انتخاب موضع یا کمبود مدرک مؤثر ایجاد کن.",
            "نتیجه حقوقی قطعی را بدون مبنای کافی به عنوان fact ثبت نکن.",
        ),
        report_sections=(
            "مشخصات پرونده و طرفین",
            "شرح و خط زمانی وقایع",
            "ادعاها و مواضع طرفین",
            "مستندات و ادله",
            "مسائل و ابهام‌های حقوقی",
            "نقاط تعارض و خلأهای اثباتی",
            "جمع‌بندی برای بررسی وکیل",
        ),
    ),
    User.Profession.TECHNICAL_EXPERT: ProfessionalPlaybook(
        key=User.Profession.TECHNICAL_EXPERT,
        title="تحلیل کارشناسی فنی",
        role="دستیار کارشناس و مشاور فنی",
        objectives=(
            "استخراج مشخصات فنی، مشاهدات، اندازه‌گیری‌ها و سوابق",
            "تفکیک observation از inference و professional opinion",
            "تحلیل علل محتمل و شواهد مؤید یا ناقض",
            "آماده‌سازی گزارش فنی قابل ردیابی تا منبع",
        ),
        analysis_dimensions=(
            "technical_context",
            "observations",
            "failure_mechanism",
            "root_cause",
            "contributing_factors",
            "standards_and_requirements",
            "impact_and_extent",
            "remediation",
            "evidence_sufficiency",
        ),
        decision_gap_rules=(
            "مشخصات و اندازه‌گیری‌های موجود در اسناد و تصاویر را دوباره نپرس.",
            "برای root cause، استاندارد قابل اعمال، کفایت شواهد و انتخاب بین علل محتمل decision gap تخصصی بساز.",
            "بین مشاهده مستقیم و استنتاج فنی تمایز صریح حفظ کن.",
        ),
        report_sections=(
            "موضوع و دامنه بررسی",
            "مدارک و مشاهدات",
            "تحلیل فنی",
            "علت‌یابی و عوامل مؤثر",
            "آثار و میزان خسارت یا نقص",
            "اقدامات اصلاحی پیشنهادی",
            "محدودیت‌های بررسی",
            "جمع‌بندی کارشناسی",
        ),
    ),
}


def resolve_playbook(case: Case) -> ProfessionalPlaybook:
    profession = getattr(case.created_by, "profession_key", "") or ""
    if profession in PLAYBOOKS:
        return PLAYBOOKS[profession]
    if case.vertical_key == "insurance" or case.sub_vertical_key == "fire_loss":
        return PLAYBOOKS[User.Profession.INSURANCE_LOSS_ADJUSTER]
    return PLAYBOOKS[User.Profession.TECHNICAL_EXPERT]


def serialize_playbook(case: Case) -> dict:
    playbook = resolve_playbook(case)
    return {
        "key": playbook.key,
        "title": playbook.title,
        "role": playbook.role,
        "specialty": getattr(case.created_by, "specialty_key", "") or "",
        "objectives": list(playbook.objectives),
        "analysis_dimensions": list(playbook.analysis_dimensions),
        "decision_gap_rules": list(playbook.decision_gap_rules),
        "report_sections": list(playbook.report_sections),
    }

from __future__ import annotations

from dataclasses import dataclass

from apps.accounts.models import User


@dataclass(frozen=True)
class CaseTypeOption:
    key: str
    label: str
    vertical_key: str
    sub_vertical_key: str


@dataclass(frozen=True)
class SpecialtyOption:
    key: str
    label: str
    case_types: tuple[CaseTypeOption, ...]


CATALOG: dict[str, tuple[SpecialtyOption, ...]] = {
    User.Profession.INSURANCE_LOSS_ADJUSTER: (
        SpecialtyOption(
            key="property_fire",
            label="آتش‌سوزی و خطرات تبعی",
            case_types=(
                CaseTypeOption("fire_loss", "خسارت آتش‌سوزی", "insurance", "fire_loss"),
                CaseTypeOption("water_damage", "ترکیدگی، نشت و آب‌دیدگی", "insurance", "property_loss"),
                CaseTypeOption("explosion_loss", "انفجار و خسارت صنعتی", "insurance", "property_loss"),
            ),
        ),
        SpecialtyOption(
            key="engineering",
            label="بیمه‌های مهندسی",
            case_types=(
                CaseTypeOption("machinery_breakdown", "شکست ماشین‌آلات", "insurance", "engineering_loss"),
                CaseTypeOption("equipment_damage", "خسارت تجهیزات و تأسیسات", "insurance", "engineering_loss"),
            ),
        ),
        SpecialtyOption(
            key="liability",
            label="بیمه مسئولیت",
            case_types=(
                CaseTypeOption("liability_claim", "پرونده خسارت مسئولیت", "insurance", "liability_claim"),
            ),
        ),
        SpecialtyOption(
            key="cargo",
            label="بیمه باربری",
            case_types=(
                CaseTypeOption("cargo_loss", "خسارت باربری", "insurance", "cargo_loss"),
            ),
        ),
    ),
    User.Profession.LAWYER: (
        SpecialtyOption(
            key="contracts",
            label="قراردادها و تعهدات",
            case_types=(
                CaseTypeOption("contract_dispute", "اختلاف قراردادی", "legal", "contract_dispute"),
                CaseTypeOption("debt_claim", "مطالبه وجه و تعهد مالی", "legal", "civil_claim"),
            ),
        ),
        SpecialtyOption(
            key="property",
            label="املاک و دعاوی ملکی",
            case_types=(
                CaseTypeOption("property_dispute", "دعوای ملکی", "legal", "property_dispute"),
            ),
        ),
        SpecialtyOption(
            key="commercial",
            label="تجاری و شرکت‌ها",
            case_types=(
                CaseTypeOption("commercial_dispute", "اختلاف تجاری", "legal", "commercial_dispute"),
            ),
        ),
        SpecialtyOption(
            key="criminal",
            label="کیفری",
            case_types=(
                CaseTypeOption("criminal_case", "پرونده کیفری", "legal", "criminal_case"),
            ),
        ),
    ),
    User.Profession.TECHNICAL_EXPERT: (
        SpecialtyOption(
            key="industrial",
            label="صنعتی و تجهیزات",
            case_types=(
                CaseTypeOption("failure_analysis", "تحلیل خرابی و علت‌یابی", "technical", "failure_analysis"),
                CaseTypeOption("technical_damage", "ارزیابی خسارت فنی", "technical", "technical_damage"),
            ),
        ),
        SpecialtyOption(
            key="construction",
            label="ساختمان و عمران",
            case_types=(
                CaseTypeOption("construction_defect", "نقص و خسارت ساختمانی", "technical", "construction"),
            ),
        ),
        SpecialtyOption(
            key="general",
            label="کارشناسی عمومی",
            case_types=(
                CaseTypeOption("technical_review", "بررسی و گزارش فنی", "technical", "general_review"),
            ),
        ),
    ),
}


def profession_options() -> list[tuple[str, str]]:
    return [(value, label) for value, label in User.Profession.choices if value != User.Profession.OTHER]


def specialties_for(profession_key: str) -> tuple[SpecialtyOption, ...]:
    return CATALOG.get(profession_key, ())


def case_types_for(profession_key: str, specialty_key: str) -> tuple[CaseTypeOption, ...]:
    for specialty in specialties_for(profession_key):
        if specialty.key == specialty_key:
            return specialty.case_types
    return ()


def find_case_type(profession_key: str, specialty_key: str, case_type_key: str) -> CaseTypeOption | None:
    for option in case_types_for(profession_key, specialty_key):
        if option.key == case_type_key:
            return option
    return None

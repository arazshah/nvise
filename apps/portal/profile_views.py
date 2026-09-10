from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.cases.models import Case
from apps.intelligence.professional_catalog import (
    case_types_for,
    find_case_type,
    profession_options,
    specialties_for,
)


@login_required
@require_http_methods(["GET", "POST"])
def professional_profile(request):
    user = request.user
    if request.method == "POST":
        action = request.POST.get("action", "profile")
        if action == "profile":
            profession = request.POST.get("profession", "").strip()
            specialty = request.POST.get("specialty", "").strip()
            valid_professions = {key for key, _ in profession_options()}
            valid_specialties = {item.key for item in specialties_for(profession)}
            if profession not in valid_professions or specialty not in valid_specialties:
                return HttpResponseBadRequest("انتخاب حرفه یا تخصص معتبر نیست.")
            user.profession_key = profession
            user.specialty_key = specialty
            user.save(update_fields=["profession_key", "specialty_key", "updated_at"])
            return redirect("portal:professional-profile")

        if action == "case_type":
            case_code = request.POST.get("case_code", "").strip()
            case_type_key = request.POST.get("case_type", "").strip()
            case = (
                Case.objects.filter(
                    case_code__iexact=case_code,
                    tenant__memberships__user=user,
                    tenant__memberships__is_active=True,
                )
                .distinct()
                .first()
            )
            if case is None:
                return HttpResponseBadRequest("پرونده معتبر نیست.")
            option = find_case_type(user.profession_key, user.specialty_key, case_type_key)
            if option is None:
                return HttpResponseBadRequest("نوع پرونده با پروفایل حرفه‌ای شما سازگار نیست.")
            case.case_type_key = option.key
            case.vertical_key = option.vertical_key
            case.sub_vertical_key = option.sub_vertical_key
            case.save(update_fields=["case_type_key", "vertical_key", "sub_vertical_key", "updated_at"])
            return redirect("portal:professional-profile")

    profession = user.profession_key or ""
    specialties = specialties_for(profession)
    selected_specialty = user.specialty_key or ""
    case_types = case_types_for(profession, selected_specialty)
    cases = list(
        Case.objects.filter(
            tenant__memberships__user=user,
            tenant__memberships__is_active=True,
            lifecycle_status=Case.LifecycleStatus.ACTIVE,
        )
        .distinct()
        .order_by("-updated_at")[:20]
    )
    return render(
        request,
        "portal/professional_profile.html",
        {
            "profession_options": profession_options(),
            "selected_profession": profession,
            "specialties": specialties,
            "selected_specialty": selected_specialty,
            "case_types": case_types,
            "cases": cases,
        },
    )

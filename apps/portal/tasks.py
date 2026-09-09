from asgiref.sync import async_to_sync
from celery import shared_task
from django.conf import settings

from apps.cases.models import Case
from apps.messaging.models import ConversationState
from apps.messaging.providers.bale import BaleProvider
from apps.system.integrations import get_bale_config

from .services import create_review_access_token


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def send_review_link(self, case_id: str) -> None:
    case = Case.objects.select_related("created_by").get(pk=case_id)
    state = (
        ConversationState.objects.filter(active_case=case, user=case.created_by, provider="bale")
        .order_by("-updated_at")
        .first()
    )
    config = get_bale_config()
    if state is None or not config.enabled or not config.bot_token:
        return
    raw_token = create_review_access_token(
        user=case.created_by,
        case=case,
        ttl_minutes=settings.REVIEW_LINK_TTL_MINUTES,
    )
    url = f"{settings.WEB_BASE_URL}/review/access/{raw_token}/"
    provider = BaleProvider(config.bot_token)
    async_to_sync(provider.send_text)(
        state.external_chat_id,
        "گزارش پرونده برای بررسی آماده است.\n\n"
        f"لینک امن بررسی و تأیید گزارش:\n{url}\n\n"
        f"این لینک {settings.REVIEW_LINK_TTL_MINUTES} دقیقه اعتبار دارد و یک‌بار مصرف است.",
    )

import hashlib
from pathlib import Path

from django.conf import settings


def store_private_bytes(*, attachment_id: str, filename: str, content: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(content).hexdigest()
    safe_name = Path(filename or "attachment.bin").name
    relative = Path(str(attachment_id)) / f"{digest[:16]}-{safe_name}"
    destination = settings.PRIVATE_MEDIA_ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(destination)

    return relative.as_posix(), digest

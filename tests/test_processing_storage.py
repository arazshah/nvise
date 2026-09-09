import hashlib

from django.test import override_settings

from apps.processing.storage import store_private_bytes


def test_private_storage_sanitizes_filename_and_hashes_content(tmp_path):
    content = b"nvise-attachment"

    with override_settings(PRIVATE_MEDIA_ROOT=tmp_path):
        storage_key, digest = store_private_bytes(
            attachment_id="attachment-1",
            filename="../../unsafe.txt",
            content=content,
        )

    assert storage_key.startswith("attachment-1/")
    assert ".." not in storage_key
    assert digest == hashlib.sha256(content).hexdigest()
    assert (tmp_path / storage_key).read_bytes() == content

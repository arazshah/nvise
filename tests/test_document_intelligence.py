import fitz

from apps.processing.document_intelligence import classify_document_text, extract_document_pages
from apps.messaging.models import CaseMessage
from apps.processing.models import ProcessingJob
from apps.processing.tasks import _enqueue_next_job, _next_job_type


def test_classifies_insurance_policy_from_document_text():
    assert (
        classify_document_text(
            "شماره بیمه‌نامه ۱۴۰۳/۱۲۳ و شرایط خصوصی بیمه نامه آتش سوزی",
            "policy.pdf",
        )
        == "insurance_policy"
    )


def test_extracts_native_pdf_text_page_by_page():
    pdf = fitz.open()
    page1 = pdf.new_page()
    page1.insert_text((72, 72), "Policy number 123456 and insured factory information " * 3)
    page2 = pdf.new_page()
    page2.insert_text((72, 72), "Inspection notes and incident date 2025-06-01 " * 3)
    content = pdf.tobytes()
    pdf.close()

    pages = extract_document_pages(
        content,
        mime_type="application/pdf",
        filename="policy.pdf",
    )

    assert len(pages) == 2
    assert pages[0]["page"] == 1
    assert pages[0]["method"] == "pdf_text"
    assert "Policy number 123456" in pages[0]["text"]
    assert pages[1]["page"] == 2
    assert "incident date" in pages[1]["text"]


def test_document_and_image_jobs_are_dispatched(monkeypatch):
    calls = []
    monkeypatch.setattr("apps.processing.tasks.extract_document.delay", lambda job_id: calls.append(("document", job_id)))
    monkeypatch.setattr("apps.processing.tasks.analyze_image.delay", lambda job_id: calls.append(("image", job_id)))

    document_job = type("Job", (), {"job_type": ProcessingJob.JobType.EXTRACT_DOCUMENT, "id": "doc-1"})()
    image_job = type("Job", (), {"job_type": ProcessingJob.JobType.ANALYZE_IMAGE, "id": "img-1"})()

    _enqueue_next_job(document_job)
    _enqueue_next_job(image_job)

    assert calls == [("document", "doc-1"), ("image", "img-1")]


def test_image_document_attachment_uses_image_analysis_job():
    assert (
        _next_job_type(
            CaseMessage.MessageType.DOCUMENT,
            mime_type="image/jpeg",
            filename="damage.jpg",
        )
        == ProcessingJob.JobType.ANALYZE_IMAGE
    )

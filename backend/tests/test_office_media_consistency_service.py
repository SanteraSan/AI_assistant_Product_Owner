from app.services.document_loader import RawDocument
from app.services.office_media_consistency_service import (
    CONSISTENCY_STATUS_POTENTIAL_MISMATCH,
    build_office_media_consistency_documents,
)


def test_build_office_media_consistency_documents_detects_potential_mismatch() -> None:
    source_path = "/tmp/sample-with-images.docx"
    documents = [
        RawDocument(
            id="docx:paragraph",
            title="sample - paragraph",
            content="The image below is a 200 by 200 pixel gradient.",
            source_type="docx",
            source_path=source_path,
            domain="documents",
        ),
        RawDocument(
            id="image:digest",
            title="sample - embedded image digest",
            content="Vision digest: На изображении представлен график прибыли.",
            source_type="image_digest",
            source_path=source_path,
            domain="documents",
            metadata={
                "file_name": "sample-with-images.docx",
                "parent_source_type": "docx",
                "embedded_path": "word/media/image1.jpg",
                "embedded_image_index": 1,
            },
        ),
        RawDocument(
            id="image:ocr",
            title="sample - embedded image OCR",
            content="OCR text: График прибыли. ДОХОД, РУБ.",
            source_type="image_ocr",
            source_path=source_path,
            domain="documents",
            metadata={
                "file_name": "sample-with-images.docx",
                "parent_source_type": "docx",
                "embedded_path": "word/media/image1.jpg",
                "embedded_image_index": 1,
            },
        ),
    ]

    consistency_documents = build_office_media_consistency_documents(documents)

    assert len(consistency_documents) == 1
    assert consistency_documents[0].source_type == "office_media_consistency"
    assert "Consistency status: potential_mismatch" in consistency_documents[0].content
    assert "Document text mentions a gradient image" in consistency_documents[0].content
    assert "200 by 200 pixel gradient" in consistency_documents[0].content
    assert "график прибыли" in consistency_documents[0].content.lower()
    assert (
        consistency_documents[0].metadata["consistency_status"]
        == CONSISTENCY_STATUS_POTENTIAL_MISMATCH
    )
    assert consistency_documents[0].metadata["parent_source_type"] == "docx"
    assert consistency_documents[0].metadata["embedded_path"] == "word/media/image1.jpg"
    assert "profit chart" in str(consistency_documents[0].metadata["consistency_reason"])


def test_build_office_media_consistency_documents_keeps_summary_in_single_chunk_budget() -> None:
    source_path = "/tmp/sample-with-images.docx"
    long_gradient_text = " ".join(
        [
            "The image below is a 200 by 200 pixel gradient.",
            "The red channel increases from left to right.",
        ]
        * 80
    )
    long_digest_text = " ".join(
        ["Vision digest: На изображении представлен график прибыли."] * 80
    )
    long_ocr_text = " ".join(["OCR text: График прибыли. ДОХОД, РУБ."] * 80)
    documents = [
        RawDocument(
            id="docx:paragraph",
            title="sample - paragraph",
            content=long_gradient_text,
            source_type="docx",
            source_path=source_path,
            domain="documents",
        ),
        RawDocument(
            id="image:digest",
            title="sample - embedded image digest",
            content=long_digest_text,
            source_type="image_digest",
            source_path=source_path,
            domain="documents",
            metadata={
                "file_name": "sample-with-images.docx",
                "parent_source_type": "docx",
                "embedded_path": "word/media/image1.jpg",
                "embedded_image_index": 1,
            },
        ),
        RawDocument(
            id="image:ocr",
            title="sample - embedded image OCR",
            content=long_ocr_text,
            source_type="image_ocr",
            source_path=source_path,
            domain="documents",
            metadata={
                "file_name": "sample-with-images.docx",
                "parent_source_type": "docx",
                "embedded_path": "word/media/image1.jpg",
                "embedded_image_index": 1,
            },
        ),
    ]

    consistency_document = build_office_media_consistency_documents(documents)[0]

    assert consistency_document.content.startswith(f"File: {source_path}")
    assert "Consistency status: potential_mismatch" in consistency_document.content[:250]
    assert len(consistency_document.content) < 1800

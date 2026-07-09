from pathlib import Path

from docx import Document
from PIL import Image

from app.services import document_loader
from app.services.document_loader import iter_office_embedded_images, load_raw_documents


def test_image_ocr_loader_extracts_text_and_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    image_path = raw_data_dir / "screenshot.png"
    Image.new("RGB", (320, 120), color="white").save(image_path)

    monkeypatch.setattr(document_loader, "_tesseract_available", lambda: True)
    monkeypatch.setattr(
        document_loader.pytesseract,
        "image_to_string",
        lambda image, lang: "Найти термин и начать обучение",
    )

    documents = load_raw_documents(raw_data_dir, tenant_id="tenant", bucket_id="bucket")

    image_documents = [document for document in documents if document.source_type == "image_ocr"]

    assert len(image_documents) == 1
    assert image_documents[0].tenant_id == "tenant"
    assert image_documents[0].bucket_id == "bucket"
    assert "Найти термин" in image_documents[0].content
    assert image_documents[0].metadata["image_width"] == 320
    assert image_documents[0].metadata["image_height"] == 120
    assert image_documents[0].metadata["ocr_engine"] == "tesseract"
    assert image_documents[0].metadata["ocr_languages"] == "rus+eng"


def test_docx_embedded_image_ocr_builds_parent_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    image_path = tmp_path / "embedded.png"
    Image.new("RGB", (100, 80), color="white").save(image_path)

    docx_path = raw_data_dir / "with-image.docx"
    document = Document()
    document.add_paragraph("Document with embedded image.")
    document.add_picture(str(image_path))
    document.save(docx_path)

    monkeypatch.setattr(document_loader, "_tesseract_available", lambda: True)
    monkeypatch.setattr(
        document_loader.pytesseract,
        "image_to_string",
        lambda image, lang: "Embedded chart text",
    )

    documents = load_raw_documents(raw_data_dir, tenant_id="tenant", bucket_id="bucket")
    embedded_ocr_documents = [
        document
        for document in documents
        if document.source_type == "image_ocr"
        and document.metadata.get("parent_source_type") == "docx"
    ]

    assert len(embedded_ocr_documents) == 1
    assert embedded_ocr_documents[0].source_path == str(docx_path)
    assert "Embedded chart text" in embedded_ocr_documents[0].content
    assert embedded_ocr_documents[0].metadata["embedded_path"].startswith("word/media/")
    assert embedded_ocr_documents[0].metadata["embedded_image_index"] == 1


def test_legacy_xls_embedded_image_extractor_finds_binary_image_blobs(tmp_path: Path) -> None:
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    image_buffer = tmp_path / "image.jpg"
    Image.new("RGB", (64, 48), color="white").save(image_buffer, format="JPEG")

    xls_path = raw_data_dir / "legacy.xls"
    xls_path.write_bytes(b"legacy-biff-prefix" + image_buffer.read_bytes() + b"legacy-biff-suffix")

    embedded_images = iter_office_embedded_images(raw_data_dir)

    assert len(embedded_images) == 1
    assert embedded_images[0].parent_path == xls_path
    assert embedded_images[0].parent_source_type == "xls"
    assert embedded_images[0].embedded_path == "legacy-binary/image1.jpg"
    assert embedded_images[0].image_index == 1

from pathlib import Path

from PIL import Image

from app.services import document_loader
from app.services.document_loader import load_raw_documents


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

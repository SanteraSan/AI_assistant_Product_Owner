from pathlib import Path

from app.services.loaders.common import (
    DEFAULT_BUCKET_ID,
    DEFAULT_TENANT_ID,
    IMAGE_OCR_EXTENSIONS,
    EmbeddedImage,
    RawDocument,
    _apply_ingestion_manifest,
    _domain_for_path,
    _embedded_image_context_lines,
    _features_from_text,
    _stable_document_id,
)
from app.services.loaders.docx import _load_docx_documents
from app.services.loaders.excel import (
    _load_excel_chart_documents,
    _load_excel_documents,
    _summarize_excel_chart_xml,
)
from app.services.loaders.images import (
    _load_image_ocr_documents,
    _load_scanned_table_image_ocr_documents,
    iter_scanned_table_images,
)
from app.services.loaders.office_images import (
    _load_office_embedded_image_ocr_documents,
    iter_office_embedded_images,
)
from app.services.loaders.text import (
    _load_csv_documents,
    _load_json_documents,
    _load_markdown_documents,
    _load_openapi_documents,
    _load_pdf_documents,
    _load_text_documents,
)


def load_raw_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    bucket_id: str = DEFAULT_BUCKET_ID,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    documents.extend(_load_markdown_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_text_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_json_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_pdf_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_docx_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_image_ocr_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_office_embedded_image_ocr_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_scanned_table_image_ocr_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_excel_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_excel_chart_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_csv_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_openapi_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents = _apply_ingestion_manifest(raw_data_dir, documents)
    return [document for document in documents if document.content.strip()]

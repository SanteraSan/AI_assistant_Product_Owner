import json
import warnings
from dataclasses import dataclass, field
from dataclasses import replace
from pathlib import Path
from typing import Any

from docx import Document
import pandas as pd
from PIL import Image
import pytesseract
from pypdf import PdfReader
import yaml

DEFAULT_TENANT_ID = "local_demo"
DEFAULT_BUCKET_ID = "taskflow_seed"
INDEXED_STATUS = "indexed"
INGESTION_MANIFEST_FILE_NAME = "ingestion_manifest.json"
DOCX_PARAGRAPH_WINDOW_SIZE = 8
DOCX_PARAGRAPH_WINDOW_OVERLAP = 2
IMAGE_OCR_EXTENSIONS = (".png", ".jpg", ".jpeg")
IMAGE_OCR_LANGUAGES = "rus+eng"


@dataclass(frozen=True)
class RawDocument:
    id: str
    title: str
    content: str
    source_type: str
    source_path: str
    domain: str
    feature: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = DEFAULT_TENANT_ID
    bucket_id: str = DEFAULT_BUCKET_ID
    processing_status: str = INDEXED_STATUS


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
    documents.extend(_load_excel_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_csv_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_openapi_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents = _apply_ingestion_manifest(raw_data_dir, documents)
    return [document for document in documents if document.content.strip()]


def _load_markdown_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    for path in sorted(raw_data_dir.rglob("*.md")):
        content = path.read_text(encoding="utf-8")
        documents.append(
            RawDocument(
                id=_stable_document_id(path),
                title=_title_from_markdown(content) or path.stem.replace("_", " ").title(),
                content=content,
                source_type=_source_type_for_path(path),
                source_path=str(path),
                domain=_domain_for_path(path),
                feature=_features_from_text(content),
                metadata={"file_name": path.name},
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )
    return documents


def _load_text_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    for path in sorted(raw_data_dir.rglob("*.txt")):
        content = path.read_text(encoding="utf-8")
        documents.append(
            RawDocument(
                id=_stable_document_id(path),
                title=path.stem.replace("_", " ").title(),
                content=content,
                source_type=_source_type_for_path(path),
                source_path=str(path),
                domain=_domain_for_path(path),
                feature=_features_from_text(content),
                metadata={"file_name": path.name},
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )
    return documents


def _load_json_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    for path in sorted(raw_data_dir.rglob("*.json")):
        if path.name == INGESTION_MANIFEST_FILE_NAME:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        content = _json_to_text(data)
        documents.append(
            RawDocument(
                id=_stable_document_id(path),
                title=_title_from_json(data) or path.stem.replace("_", " ").title(),
                content=content,
                source_type=_source_type_for_path(path),
                source_path=str(path),
                domain=_domain_for_path(path),
                feature=_features_from_text(content),
                metadata={"file_name": path.name},
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )
    return documents


def _load_pdf_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    for path in sorted(raw_data_dir.rglob("*.pdf")):
        reader = PdfReader(path)
        page_count = len(reader.pages)
        for page_index, page in enumerate(reader.pages, start=1):
            content = (page.extract_text() or "").strip()
            documents.append(
                RawDocument(
                    id=f"{_stable_document_id(path)}:page:{page_index}",
                    title=f"{path.stem.replace('_', ' ').title()} - page {page_index}",
                    content=content,
                    source_type="pdf",
                    source_path=str(path),
                    domain=_domain_for_path(path),
                    feature=_features_from_text(content),
                    metadata={
                        "file_name": path.name,
                        "page_number": page_index,
                        "page_count": page_count,
                    },
                    tenant_id=tenant_id,
                    bucket_id=bucket_id,
                )
            )
    return documents


def _load_csv_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    for path in sorted(raw_data_dir.rglob("*.csv")):
        frame = pd.read_csv(path)
        for index, row in frame.fillna("").iterrows():
            row_data = {key: str(value) for key, value in row.to_dict().items()}
            title = row_data.get("subject") or row_data.get("review_id") or row_data.get("metric_type") or path.stem
            feature = _split_features(row_data.get("feature", ""))
            documents.append(
                RawDocument(
                    id=f"{_stable_document_id(path)}:{index}",
                    title=str(title),
                    content=_row_to_text(row_data),
                    source_type=_source_type_for_path(path),
                    source_path=str(path),
                    domain=_domain_for_path(path),
                    feature=feature,
                    metadata={"row_index": int(index), "file_name": path.name, **row_data},
                    tenant_id=tenant_id,
                    bucket_id=bucket_id,
                )
            )
    return documents


def _load_docx_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    for path in sorted(raw_data_dir.rglob("*.docx")):
        docx_document = Document(path)
        paragraphs = [
            (paragraph_index, paragraph.text.strip())
            for paragraph_index, paragraph in enumerate(docx_document.paragraphs)
            if paragraph.text.strip()
        ]
        block_index = 0
        for position, (paragraph_index, content) in enumerate(paragraphs):
            block_index += 1
            previous_content = paragraphs[position - 1][1] if position > 0 else ""
            next_content = paragraphs[position + 1][1] if position + 1 < len(paragraphs) else ""
            documents.append(
                RawDocument(
                    id=f"{_stable_document_id(path)}:paragraph:{paragraph_index}",
                    title=f"{path.stem} - paragraph {paragraph_index + 1}",
                    content="\n".join(
                        [
                            f"File: {path.name}",
                            f"Block type: paragraph",
                            f"Previous paragraph: {previous_content}" if previous_content else "",
                            f"Current paragraph: {content}",
                            f"Next paragraph: {next_content}" if next_content else "",
                        ]
                    ),
                    source_type="docx",
                    source_path=str(path),
                    domain=_domain_for_path(path),
                    feature=_features_from_text(content),
                    metadata={
                        "file_name": path.name,
                        "block_type": "paragraph",
                        "block_index": block_index,
                        "paragraph_index": paragraph_index,
                    },
                    tenant_id=tenant_id,
                    bucket_id=bucket_id,
                )
            )

        documents.extend(
            _build_docx_paragraph_windows(
                path,
                paragraphs,
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )

        for table_index, table in enumerate(docx_document.tables):
            for row_index, row in enumerate(table.rows):
                row_values = [
                    cell.text.strip()
                    for cell in row.cells
                    if cell.text.strip()
                ]
                if not row_values:
                    continue
                block_index += 1
                content = "\n".join(
                    [
                        f"File: {path.name}",
                        f"Block type: table_row",
                        f"Table: {table_index + 1}",
                        f"Row values: {' | '.join(row_values)}",
                    ]
                )
                documents.append(
                    RawDocument(
                        id=f"{_stable_document_id(path)}:table:{table_index}:row:{row_index}",
                        title=f"{path.stem} - table {table_index + 1} row {row_index + 1}",
                        content=content,
                        source_type="docx",
                        source_path=str(path),
                        domain=_domain_for_path(path),
                        feature=_features_from_text(content),
                        metadata={
                            "file_name": path.name,
                            "block_type": "table_row",
                            "block_index": block_index,
                            "table_index": table_index,
                            "table_row_index": row_index,
                        },
                        tenant_id=tenant_id,
                        bucket_id=bucket_id,
                    )
                )
    return documents


def _load_image_ocr_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    image_paths = sorted(
        path
        for extension in IMAGE_OCR_EXTENSIONS
        for path in raw_data_dir.rglob(f"*{extension}")
    )
    if not image_paths:
        return documents

    if not _tesseract_available():
        warnings.warn(
            (
                "Tesseract OCR is not available. Image OCR ingestion skipped. "
                "Install system packages: tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng."
            ),
            RuntimeWarning,
            stacklevel=2,
        )
        return documents

    for path in image_paths:
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format or path.suffix.lstrip(".").upper()
            content = pytesseract.image_to_string(image, lang=IMAGE_OCR_LANGUAGES).strip()
        if not content:
            continue

        documents.append(
            RawDocument(
                id=f"{_stable_document_id(path)}:ocr",
                title=f"{path.stem} - OCR text",
                content="\n".join(
                    [
                        f"File: {path.name}",
                        "Block type: image_ocr",
                        "OCR text:",
                        content,
                    ]
                ),
                source_type="image_ocr",
                source_path=str(path),
                domain=_domain_for_path(path),
                feature=_features_from_text(content),
                metadata={
                    "file_name": path.name,
                    "block_type": "image_ocr",
                    "image_width": width,
                    "image_height": height,
                    "image_format": image_format,
                    "ocr_engine": "tesseract",
                    "ocr_languages": IMAGE_OCR_LANGUAGES,
                },
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )
    return documents


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        return False
    return True


def _build_docx_paragraph_windows(
    path: Path,
    paragraphs: list[tuple[int, str]],
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    if len(paragraphs) < 2:
        return []

    documents: list[RawDocument] = []
    step = max(1, DOCX_PARAGRAPH_WINDOW_SIZE - DOCX_PARAGRAPH_WINDOW_OVERLAP)
    for window_index, start in enumerate(range(0, len(paragraphs), step)):
        window = paragraphs[start : start + DOCX_PARAGRAPH_WINDOW_SIZE]
        if not window:
            continue

        paragraph_start_index = window[0][0]
        paragraph_end_index = window[-1][0]
        paragraph_lines = [
            f"Paragraph {paragraph_index + 1}: {content}"
            for paragraph_index, content in window
        ]
        content = "\n".join(
            [
                f"File: {path.name}",
                "Block type: paragraph_window",
                f"Paragraph range: {paragraph_start_index + 1}-{paragraph_end_index + 1}",
                *paragraph_lines,
            ]
        )
        documents.append(
            RawDocument(
                id=f"{_stable_document_id(path)}:paragraph_window:{window_index}",
                title=f"{path.stem} - paragraphs {paragraph_start_index + 1}-{paragraph_end_index + 1}",
                content=content,
                source_type="docx",
                source_path=str(path),
                domain=_domain_for_path(path),
                feature=_features_from_text(content),
                metadata={
                    "file_name": path.name,
                    "block_type": "paragraph_window",
                    "window_index": window_index,
                    "paragraph_start_index": paragraph_start_index,
                    "paragraph_end_index": paragraph_end_index,
                    "paragraph_count": len(window),
                },
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )
    return documents


def _load_excel_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    excel_paths = sorted(
        list(raw_data_dir.rglob("*.xlsx"))
        + list(raw_data_dir.rglob("*.xls"))
    )
    for path in excel_paths:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str)
        for sheet_name, frame in sheets.items():
            for index, row in frame.fillna("").iterrows():
                row_data = {key: str(value) for key, value in row.to_dict().items()}
                content = "\n".join(
                    [
                        f"File: {path.name}",
                        f"Sheet: {sheet_name}",
                        f"Row values: {_compact_row_values(row_data)}",
                        _row_to_text(row_data),
                    ]
                )
                title = f"{path.stem} - {sheet_name} - row {int(index) + 2}"
                documents.append(
                    RawDocument(
                        id=f"{_stable_document_id(path)}:{sheet_name}:{index}",
                        title=title,
                        content=content,
                        source_type="excel_row",
                        source_path=str(path),
                        domain=_domain_for_path(path),
                        feature=_features_from_text(content),
                        metadata={
                            "file_name": path.name,
                            "sheet_name": sheet_name,
                            "row_index": int(index),
                            "excel_row_number": int(index) + 2,
                            **row_data,
                        },
                        tenant_id=tenant_id,
                        bucket_id=bucket_id,
                    )
                )
    return documents


def _load_openapi_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    for path in sorted(list(raw_data_dir.rglob("*.yaml")) + list(raw_data_dir.rglob("*.yml"))):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        paths = data.get("paths", {})
        for route, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                operation_id = operation.get("operationId", f"{method}_{route}")
                summary = operation.get("summary", "")
                tags = operation.get("tags", [])
                responses = ", ".join(str(code) for code in operation.get("responses", {}).keys())
                content = "\n".join(
                    [
                        f"Endpoint: {method.upper()} {route}",
                        f"Operation ID: {operation_id}",
                        f"Summary: {summary}",
                        f"Tags: {', '.join(tags) if isinstance(tags, list) else tags}",
                        f"Responses: {responses}",
                    ]
                )
                documents.append(
                    RawDocument(
                        id=f"{_stable_document_id(path)}:{method}:{route}",
                        title=f"{method.upper()} {route}",
                        content=content,
                        source_type="openapi",
                        source_path=str(path),
                        domain="tech_knowledge",
                        feature=_features_from_text(content),
                        metadata={
                            "method": method.upper(),
                            "path": route,
                            "operation_id": operation_id,
                            "tags": tags,
                            "file_name": path.name,
                        },
                        tenant_id=tenant_id,
                        bucket_id=bucket_id,
                    )
                )
    return documents


def _title_from_markdown(content: str) -> str | None:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _title_from_json(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("title", "name", "id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _source_type_for_path(path: Path) -> str:
    parts = set(path.parts)
    if path.suffix == ".csv":
        if "business_metrics" in parts:
            return "metric_row"
        if "user_feedback" in parts:
            return "support_ticket"
    if "release_notes" in parts:
        return "incident_note" if "incident" in path.name else "release_note"
    if "tech_knowledge" in parts:
        return "markdown"
    return path.suffix.lstrip(".") or "text"


def _domain_for_path(path: Path) -> str:
    for domain in ("tech_knowledge", "user_feedback", "business_metrics", "release_notes"):
        if domain in path.parts:
            return domain
    return "documents"


def _stable_document_id(path: Path) -> str:
    return path.as_posix().replace("/", "_").replace(".", "_")


def _apply_ingestion_manifest(
    raw_data_dir: Path,
    documents: list[RawDocument],
) -> list[RawDocument]:
    manifest_path = raw_data_dir / INGESTION_MANIFEST_FILE_NAME
    if not manifest_path.exists():
        return documents

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = data.get("documents", []) if isinstance(data, dict) else []
    overrides_by_path = {
        str(entry.get("path")): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("path")
    }
    if not overrides_by_path:
        return documents

    updated_documents: list[RawDocument] = []
    for document in documents:
        relative_path = Path(document.source_path).relative_to(raw_data_dir).as_posix()
        override = overrides_by_path.get(relative_path)
        if not override:
            updated_documents.append(document)
            continue

        metadata = dict(document.metadata)
        metadata.update(_as_dict(override.get("metadata")))
        updated_documents.append(
            replace(
                document,
                tenant_id=str(override.get("tenant_id") or document.tenant_id),
                bucket_id=str(override.get("bucket_id") or document.bucket_id),
                source_type=str(override.get("source_type") or document.source_type),
                feature=_as_str_list(override.get("features")) or document.feature,
                metadata=metadata,
            )
        )
    return updated_documents


def _features_from_text(text: str) -> list[str]:
    known_features = [
        "tasks",
        "projects",
        "sprints",
        "notifications",
        "permissions",
        "csv_import",
        "search",
        "reports",
        "webhooks",
        "integrations",
    ]
    lowered = text.lower()
    return [feature for feature in known_features if feature.lower() in lowered]


def _split_features(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _row_to_text(row: dict[str, str]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in row.items() if value)


def _compact_row_values(row: dict[str, str]) -> str:
    return " | ".join(value.strip() for value in row.values() if value.strip())


def _json_to_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)

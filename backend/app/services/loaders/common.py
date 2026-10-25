from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
import pytesseract

DEFAULT_TENANT_ID = "local_demo"
DEFAULT_BUCKET_ID = "taskflow_seed"
INDEXED_STATUS = "indexed"
INGESTION_MANIFEST_FILE_NAME = "ingestion_manifest.json"
DOCX_PARAGRAPH_WINDOW_SIZE = 8
DOCX_PARAGRAPH_WINDOW_OVERLAP = 2
IMAGE_OCR_EXTENSIONS = (".png", ".jpg", ".jpeg")
IMAGE_OCR_LANGUAGES = "rus+eng"
OFFICE_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")
DOCX_MEDIA_PREFIX = "word/media/"
XLSX_MEDIA_PREFIX = "xl/media/"
LEGACY_XLS_EMBEDDED_IMAGE_LIMIT = 50
SCANNED_TABLE_MIN_GRID_LINES = 3
SCANNED_TABLE_LINE_RATIO = 0.25
SCANNED_TABLE_CELL_PADDING = 4
OFFICE_XML_NAMESPACES = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


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


@dataclass(frozen=True)
class EmbeddedImage:
    parent_path: Path
    embedded_path: str
    image_index: int
    content: bytes
    parent_source_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


def ocr_image_text(image: Image.Image) -> str:
    return pytesseract.image_to_string(image, lang=IMAGE_OCR_LANGUAGES).strip()


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        return False
    return True


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


def _open_embedded_image(embedded_image: EmbeddedImage) -> tuple[Image.Image, int, int, str]:
    image = Image.open(BytesIO(embedded_image.content))
    width, height = image.size
    image_format = image.format or Path(embedded_image.embedded_path).suffix.lstrip(".").upper()
    return image, width, height, image_format


def _embedded_image_context_lines(metadata: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if metadata.get("anchor_type"):
        lines.append(f"Anchor type: {metadata['anchor_type']}")
    if metadata.get("sheet_name"):
        lines.append(f"Sheet: {metadata['sheet_name']}")
    if metadata.get("anchor_cell"):
        lines.append(f"Anchor cell: {metadata['anchor_cell']}")
    if metadata.get("table_index") is not None:
        lines.append(
            "Table position: "
            f"table {int(metadata['table_index']) + 1}, "
            f"row {int(metadata.get('table_row_index', 0)) + 1}, "
            f"cell {int(metadata.get('table_cell_index', 0)) + 1}"
        )
    linked_text = str(metadata.get("linked_text") or "").strip()
    if linked_text:
        lines.append(f"Linked text: {linked_text}")
    return lines


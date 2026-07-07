import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

DEFAULT_TENANT_ID = "local_demo"
DEFAULT_BUCKET_ID = "taskflow_seed"
INDEXED_STATUS = "indexed"


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
    documents.extend(_load_csv_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
    documents.extend(_load_openapi_documents(raw_data_dir, tenant_id=tenant_id, bucket_id=bucket_id))
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


def _row_to_text(row: dict[str, str]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in row.items() if value)


def _json_to_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)

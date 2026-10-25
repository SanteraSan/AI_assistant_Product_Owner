from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from pypdf import PdfReader
import yaml

from app.services.hh_resume_sections import split_hh_resume
from app.services.loaders.common import (
    INGESTION_MANIFEST_FILE_NAME,
    RawDocument,
    _domain_for_path,
    _features_from_text,
    _json_to_text,
    _row_to_text,
    _source_type_for_path,
    _split_features,
    _stable_document_id,
    _title_from_json,
    _title_from_markdown,
)


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
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        resume_sections = split_hh_resume(pages)
        if resume_sections:
            for index, section in enumerate(resume_sections, start=1):
                documents.append(
                    RawDocument(
                        id=f"{_stable_document_id(path)}:resume:{index}",
                        title=f"{path.stem.replace('_', ' ').title()} - {section.title}",
                        content=section.content,
                        source_type="pdf",
                        source_path=str(path),
                        domain=_domain_for_path(path),
                        feature=_features_from_text(section.content),
                        metadata={
                            "file_name": path.name,
                            "page_number": section.page_number,
                            "page_count": page_count,
                            "resume_section": section.kind,
                            "organization": section.organization,
                        },
                        tenant_id=tenant_id,
                        bucket_id=bucket_id,
                    )
                )
            continue
        for page_index, page_text in enumerate(pages, start=1):
            if not page_text:
                continue
            documents.append(
                RawDocument(
                    id=f"{_stable_document_id(path)}:page:{page_index}",
                    title=f"{path.stem.replace('_', ' ').title()} - page {page_index}",
                    content=page_text,
                    source_type="pdf",
                    source_path=str(path),
                    domain=_domain_for_path(path),
                    feature=_features_from_text(page_text),
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


#!/usr/bin/env python3
"""Write sales markdown fixtures and merge synthetic=true into ingestion_manifest.json."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.sales_demo_data import SALES_DOCUMENT_SPECS


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    raw_dir = repo_root / "data" / "raw"
    manifest_path = raw_dir / "ingestion_manifest.json"

    for spec in SALES_DOCUMENT_SPECS:
        target = raw_dir / spec.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec.body.strip() + "\n", encoding="utf-8")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = payload.get("documents")
    if not isinstance(documents, list):
        documents = []
    by_path = {
        str(entry.get("path")): entry
        for entry in documents
        if isinstance(entry, dict) and entry.get("path")
    }
    for spec in SALES_DOCUMENT_SPECS:
        metadata = {"synthetic": True, **spec.metadata}
        by_path[spec.relative_path] = {
            "path": spec.relative_path,
            "tenant_id": "local_demo",
            "bucket_id": spec.bucket_id,
            "source_type": spec.source_type,
            "features": list(spec.features),
            "metadata": metadata,
        }
    payload["documents"] = list(by_path.values())
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(SALES_DOCUMENT_SPECS)} sales documents")
    print(f"Manifest entries: {len(payload['documents'])}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Register sales fixtures in ingestion_manifest.json.

Markdown on disk is the source of truth. This script writes `spec.body` only
when the target file is missing, so a later render cannot wipe edited demos.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.sales_demo_data import SALES_DOCUMENT_SPECS


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    raw_dir = repo_root / "data" / "raw"
    manifest_path = raw_dir / "ingestion_manifest.json"

    written = 0
    preserved = 0
    for spec in SALES_DOCUMENT_SPECS:
        target = raw_dir / spec.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            preserved += 1
            continue
        if not spec.body.strip():
            raise SystemExit(f"missing sales fixture body for {spec.relative_path}")
        target.write_text(spec.body.strip() + "\n", encoding="utf-8")
        written += 1

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
    print(f"Preserved {preserved} existing sales documents")
    print(f"Wrote {written} new sales documents")
    print(f"Manifest entries: {len(payload['documents'])}")


if __name__ == "__main__":
    main()

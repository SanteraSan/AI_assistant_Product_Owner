from pathlib import Path

from app.db.models import DocumentAsset
from app.services.document_indexing_service import _load_raw_documents_for_asset


def test_load_raw_documents_for_asset_isolates_single_file(tmp_path: Path) -> None:
    target_path = tmp_path / "target.txt"
    target_path.write_text("Target document content", encoding="utf-8")
    unrelated_path = tmp_path / "unrelated.txt"
    unrelated_path.write_text("Unrelated document content", encoding="utf-8")
    document = DocumentAsset(
        id="document-1",
        tenant_id="tenant-a",
        owner_user_id="user-a",
        title="target.txt",
        file_name="target.txt",
        source_type="txt",
        source_path=str(target_path),
        status="indexing",
        visibility="private",
        allowed_roles=[],
        size_bytes=target_path.stat().st_size,
        metadata_json={},
    )

    raw_documents = _load_raw_documents_for_asset(document=document, bucket_id="bucket-a")

    assert len(raw_documents) == 1
    assert raw_documents[0].source_path == str(target_path)
    assert raw_documents[0].tenant_id == "tenant-a"
    assert raw_documents[0].bucket_id == "bucket-a"
    assert "Target document content" in raw_documents[0].content
    assert "Unrelated document content" not in raw_documents[0].content

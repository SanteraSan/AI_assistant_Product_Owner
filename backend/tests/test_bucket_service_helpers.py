from datetime import UTC, datetime, timedelta

from app.db.models import DocumentAsset
from app.services.bucket_service import _deduplicate_available_documents


def test_deduplicate_available_documents_prefers_indexed_duplicate() -> None:
    created_at = datetime(2026, 7, 12, tzinfo=UTC)
    failed = DocumentAsset(
        id="failed",
        tenant_id="tenant",
        owner_user_id="user",
        title="images.jpeg",
        file_name="images.jpeg",
        source_type="jpeg",
        source_path="/tmp/failed_images.jpeg",
        status="index_failed",
        visibility="private",
        allowed_roles=[],
        size_bytes=53259,
        metadata_json={},
        created_at=created_at + timedelta(minutes=2),
    )
    indexed = DocumentAsset(
        id="indexed",
        tenant_id="tenant",
        owner_user_id="user",
        title="images.jpeg",
        file_name="images.jpeg",
        source_type="jpeg",
        source_path="/tmp/indexed_images.jpeg",
        status="indexed",
        visibility="private",
        allowed_roles=[],
        size_bytes=53259,
        metadata_json={},
        created_at=created_at,
    )

    documents = _deduplicate_available_documents([failed, indexed])

    assert [document.id for document in documents] == ["indexed"]

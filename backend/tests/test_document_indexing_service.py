from pathlib import Path

import pytest
from PIL import Image

from app.db.models import DocumentAsset
from app.services.document_indexing_service import (
    _can_build_image_digest,
    _load_image_digest_documents_for_asset,
    _load_raw_documents_for_asset,
)


class _FakeVisionClient:
    async def generate(self, *args, **kwargs):
        return {"response": "На изображении большое дерево на травянистом холме под голубым небом."}


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


@pytest.mark.anyio
async def test_image_digest_fallback_builds_visual_evidence_for_image_without_text(tmp_path: Path) -> None:
    target_path = tmp_path / "tree.png"
    Image.new("RGB", (320, 200), color="green").save(target_path)
    document = DocumentAsset(
        id="document-image",
        tenant_id="tenant-a",
        owner_user_id="user-a",
        title="tree.png",
        file_name="tree.png",
        source_type="png",
        source_path=str(target_path),
        status="indexing",
        visibility="private",
        allowed_roles=[],
        size_bytes=target_path.stat().st_size,
        metadata_json={},
    )

    raw_documents = await _load_image_digest_documents_for_asset(
        document=document,
        bucket_id="bucket-a",
        ollama_client=_FakeVisionClient(),  # type: ignore[arg-type]
        vision_model="vision-model",
    )

    assert len(raw_documents) == 1
    assert raw_documents[0].source_type == "image_digest"
    assert raw_documents[0].source_path == str(target_path)
    assert raw_documents[0].metadata["document_file_name"] == "tree.png"
    assert "большое дерево" in raw_documents[0].content


def test_image_digest_fallback_is_enabled_only_for_supported_images(tmp_path: Path) -> None:
    image_document = DocumentAsset(source_type="png", source_path=str(tmp_path / "tree.png"))
    text_document = DocumentAsset(source_type="txt", source_path=str(tmp_path / "notes.txt"))

    assert _can_build_image_digest(document=image_document, enabled=True, vision_model="vision")
    assert not _can_build_image_digest(document=image_document, enabled=False, vision_model="vision")
    assert not _can_build_image_digest(document=image_document, enabled=True, vision_model="")
    assert not _can_build_image_digest(document=text_document, enabled=True, vision_model="vision")

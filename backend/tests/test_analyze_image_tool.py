from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.access_policy import UserContext
from app.services.tools.analyze_image import AnalyzeImageArgs, AnalyzeImageTool
from app.services.tools.base import ToolContext


def _user(*roles: str) -> UserContext:
    return UserContext(tenant_id="t1", user_id="u1", roles=frozenset(roles))


@pytest.mark.anyio
async def test_analyze_image_returns_digest(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "car.png"
    image_path.write_bytes(b"fake-image-bytes")

    document = SimpleNamespace(
        id="doc-img",
        file_name="car.png",
        source_type="png",
        source_path=str(image_path),
    )

    class _Buckets:
        async def get_document(self, *, user, document_id):
            assert document_id == "doc-img"
            return document

        async def list_available_documents(self, *, user):
            return [document]

    class _Storage:
        def exists(self, ref: str) -> bool:
            return ref == str(image_path)

        def materialize(self, ref: str, destination: Path) -> None:
            destination.write_bytes(image_path.read_bytes())

    class _Ollama:
        pass

    async def _fake_digest(path, *, question, ollama_client, vision_model, previous_digest=None):
        del path, ollama_client, vision_model, previous_digest
        assert "авто" in question or "картин" in question or question
        return {
            "content": "На картинке красный автомобиль.",
            "image_width": 10,
            "image_height": 10,
            "image_format": "PNG",
        }

    monkeypatch.setattr(
        "app.services.tools.analyze_image.build_targeted_image_digest",
        _fake_digest,
    )

    tool = AnalyzeImageTool(
        bucket_service=_Buckets(),  # type: ignore[arg-type]
        ollama_client=_Ollama(),  # type: ignore[arg-type]
        object_storage=_Storage(),  # type: ignore[arg-type]
        vision_model="vision-test",
        vision_enabled=True,
    )
    ctx = ToolContext(user=_user("admin"), request_id="req-img", extras={})
    result = await tool.run(
        ctx,
        AnalyzeImageArgs(question="Что изображено на картинке с авто?", file_name="car.png"),
    )
    assert result.ok
    assert "красный автомобиль" in result.data["digest"]
    assert result.data["sources"][0]["source_type"] == "image_targeted_digest"

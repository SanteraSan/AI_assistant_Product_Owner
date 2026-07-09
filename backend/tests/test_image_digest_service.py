from pathlib import Path

from PIL import Image

from app.services.image_digest_service import load_image_digest_documents


class _FakeOllamaClient:
    def __init__(self) -> None:
        self.generate_kwargs = {}

    async def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return {"response": "На изображении видна надпись UFA и человек рядом."}


def test_load_image_digest_documents_builds_digest_metadata(tmp_path: Path) -> None:
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    image_path = raw_data_dir / "photo.png"
    Image.new("RGB", (640, 480), color="white").save(image_path)
    ollama_client = _FakeOllamaClient()

    async def run_loader():
        return await load_image_digest_documents(
            raw_data_dir,
            ollama_client=ollama_client,
            vision_model="vision-model",
            tenant_id="tenant",
            bucket_id="bucket",
        )

    import asyncio

    documents = asyncio.run(run_loader())

    assert len(documents) == 1
    assert documents[0].source_type == "image_digest"
    assert documents[0].tenant_id == "tenant"
    assert documents[0].bucket_id == "bucket"
    assert "надпись UFA" in documents[0].content
    assert documents[0].metadata["image_width"] == 640
    assert documents[0].metadata["image_height"] == 480
    assert documents[0].metadata["vision_model"] == "vision-model"
    assert documents[0].metadata["digest_type"] == "vision_caption"
    assert ollama_client.generate_kwargs["images"]

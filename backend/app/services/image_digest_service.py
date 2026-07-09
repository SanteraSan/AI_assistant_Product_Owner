import base64
from io import BytesIO
import warnings
from pathlib import Path
from typing import Any

from PIL import Image

from app.services.document_loader import (
    DEFAULT_BUCKET_ID,
    DEFAULT_TENANT_ID,
    IMAGE_OCR_EXTENSIONS,
    EmbeddedImage,
    RawDocument,
    _domain_for_path,
    _embedded_image_context_lines,
    _features_from_text,
    _stable_document_id,
    iter_office_embedded_images,
    iter_scanned_table_images,
)
from app.services.ollama_client import OllamaClient

IMAGE_DIGEST_PROMPT = """Опиши изображение на русском языке как evidence для RAG.

Правила:
- Если есть текст, перечисли ключевые надписи.
- Если это график или диаграмма, опиши видимый смысл, тренд, подписи и числа.
- Если это фото, кратко опиши сцену и видимые объекты.
- Не выдумывай детали, которых не видно.
- Ответ должен быть компактным, 3-8 предложений.
"""


async def load_image_digest_documents(
    raw_data_dir: Path,
    *,
    ollama_client: OllamaClient,
    vision_model: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    bucket_id: str = DEFAULT_BUCKET_ID,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    for path in _image_paths(raw_data_dir):
        try:
            digest = await _build_image_digest(
                path,
                ollama_client=ollama_client,
                vision_model=vision_model,
            )
        except Exception as exc:
            warnings.warn(
                f"Image vision digest skipped for {path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            continue
        if not digest["content"].strip():
            continue

        documents.append(
            RawDocument(
                id=f"{_stable_document_id(path)}:vision_digest",
                title=f"{path.stem} - vision digest",
                content="\n".join(
                    [
                        f"File: {path.name}",
                        "Block type: image_digest",
                        "Vision digest:",
                        digest["content"],
                    ]
                ),
                source_type="image_digest",
                source_path=str(path),
                domain=_domain_for_path(path),
                feature=_features_from_text(digest["content"]),
                metadata={
                    "file_name": path.name,
                    "block_type": "image_digest",
                    "image_width": digest["image_width"],
                    "image_height": digest["image_height"],
                    "image_format": digest["image_format"],
                    "vision_model": vision_model,
                    "digest_type": "vision_caption",
                },
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )

    for embedded_image in iter_office_embedded_images(raw_data_dir):
        documents.extend(
            await _load_embedded_image_digest_documents(
                [embedded_image],
                ollama_client=ollama_client,
                vision_model=vision_model,
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )

    documents.extend(
        await _load_embedded_image_digest_documents(
            iter_scanned_table_images(raw_data_dir),
            ollama_client=ollama_client,
            vision_model=vision_model,
            tenant_id=tenant_id,
            bucket_id=bucket_id,
        )
    )
    return documents


async def _load_embedded_image_digest_documents(
    embedded_images: list[EmbeddedImage],
    *,
    ollama_client: OllamaClient,
    vision_model: str,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    for embedded_image in embedded_images:
        try:
            digest = await _build_embedded_image_digest(
                embedded_image,
                ollama_client=ollama_client,
                vision_model=vision_model,
            )
        except Exception as exc:
            warnings.warn(
                (
                    "Embedded image vision digest skipped for "
                    f"{embedded_image.parent_path}:{embedded_image.embedded_path}: {exc}"
                ),
                RuntimeWarning,
                stacklevel=2,
            )
            continue
        if not digest["content"].strip():
            continue

        parent_path = embedded_image.parent_path
        documents.append(
            RawDocument(
                id=f"{_stable_document_id(parent_path)}:embedded_image:{embedded_image.image_index}:vision_digest",
                title=f"{parent_path.stem} - embedded image {embedded_image.image_index} vision digest",
                content="\n".join(
                    [
                        f"File: {parent_path.name}",
                        f"Embedded image: {embedded_image.embedded_path}",
                        "Block type: image_digest",
                        *_embedded_image_context_lines(embedded_image.metadata),
                        "Vision digest:",
                        digest["content"],
                    ]
                ),
                source_type="image_digest",
                source_path=str(parent_path),
                domain=_domain_for_path(parent_path),
                feature=_features_from_text(digest["content"]),
                metadata={
                    "file_name": parent_path.name,
                    "block_type": "image_digest",
                    "parent_source_type": embedded_image.parent_source_type,
                    "embedded_path": embedded_image.embedded_path,
                    "embedded_image_index": embedded_image.image_index,
                    "image_width": digest["image_width"],
                    "image_height": digest["image_height"],
                    "image_format": digest["image_format"],
                    "vision_model": vision_model,
                    "digest_type": "vision_caption",
                    **embedded_image.metadata,
                },
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )
    return documents


def _image_paths(raw_data_dir: Path) -> list[Path]:
    return sorted(
        path
        for extension in IMAGE_OCR_EXTENSIONS
        for path in raw_data_dir.rglob(f"*{extension}")
    )


async def _build_image_digest(
    path: Path,
    *,
    ollama_client: OllamaClient,
    vision_model: str,
) -> dict[str, Any]:
    with Image.open(path) as image:
        width, height = image.size
        image_format = image.format or path.suffix.lstrip(".").upper()
        encoded = _encode_image_as_png(image)

    result = await ollama_client.generate(
        model=vision_model,
        prompt=IMAGE_DIGEST_PROMPT,
        images=[encoded],
        think=False,
    )
    return {
        "content": str(result.get("response") or "").strip(),
        "image_width": width,
        "image_height": height,
        "image_format": image_format,
    }


async def _build_embedded_image_digest(
    embedded_image: EmbeddedImage,
    *,
    ollama_client: OllamaClient,
    vision_model: str,
) -> dict[str, Any]:
    with Image.open(BytesIO(embedded_image.content)) as image:
        width, height = image.size
        image_format = image.format or Path(embedded_image.embedded_path).suffix.lstrip(".").upper()
        encoded = _encode_image_as_png(image)

    result = await ollama_client.generate(
        model=vision_model,
        prompt=IMAGE_DIGEST_PROMPT,
        images=[encoded],
        think=False,
    )
    return {
        "content": str(result.get("response") or "").strip(),
        "image_width": width,
        "image_height": height,
        "image_format": image_format,
    }


def _encode_image_as_png(image: Image.Image) -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")

from __future__ import annotations

import warnings
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from app.services.loaders import common
from app.services.loaders.common import (
    IMAGE_OCR_EXTENSIONS,
    IMAGE_OCR_LANGUAGES,
    SCANNED_TABLE_CELL_PADDING,
    SCANNED_TABLE_LINE_RATIO,
    SCANNED_TABLE_MIN_GRID_LINES,
    EmbeddedImage,
    RawDocument,
    _domain_for_path,
    _embedded_image_context_lines,
    _features_from_text,
    _open_embedded_image,
    _stable_document_id,
)


def _load_image_ocr_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    documents: list[RawDocument] = []
    image_paths = _image_paths(raw_data_dir)
    if not image_paths:
        return documents

    if not common._tesseract_available():
        warnings.warn(
            (
                "Tesseract OCR is not available. Image OCR ingestion skipped. "
                "Install system packages: tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng."
            ),
            RuntimeWarning,
            stacklevel=2,
        )
        return documents

    for path in image_paths:
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format or path.suffix.lstrip(".").upper()
            content = common.ocr_image_text(image)
        if not content:
            continue

        documents.append(
            RawDocument(
                id=f"{_stable_document_id(path)}:ocr",
                title=f"{path.stem} - OCR text",
                content="\n".join(
                    [
                        f"File: {path.name}",
                        "Block type: image_ocr",
                        "OCR text:",
                        content,
                    ]
                ),
                source_type="image_ocr",
                source_path=str(path),
                domain=_domain_for_path(path),
                feature=_features_from_text(content),
                metadata={
                    "file_name": path.name,
                    "block_type": "image_ocr",
                    "image_width": width,
                    "image_height": height,
                    "image_format": image_format,
                    "ocr_engine": "tesseract",
                    "ocr_languages": IMAGE_OCR_LANGUAGES,
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


def _load_scanned_table_image_ocr_documents(
    raw_data_dir: Path,
    *,
    tenant_id: str,
    bucket_id: str,
) -> list[RawDocument]:
    if not common._tesseract_available():
        return []

    documents: list[RawDocument] = []
    for embedded_image in iter_scanned_table_images(raw_data_dir):
        try:
            image, width, height, image_format = _open_embedded_image(embedded_image)
            content = common.ocr_image_text(image)
        except Exception as exc:
            warnings.warn(
                f"Scanned table image OCR skipped for {embedded_image.parent_path}:{embedded_image.embedded_path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            continue
        if not content:
            continue

        parent_path = embedded_image.parent_path
        documents.append(
            RawDocument(
                id=f"{_stable_document_id(parent_path)}:scanned_table_image:{embedded_image.image_index}:ocr",
                title=f"{parent_path.stem} - scanned table image {embedded_image.image_index} OCR text",
                content="\n".join(
                    [
                        f"File: {parent_path.name}",
                        f"Embedded image: {embedded_image.embedded_path}",
                        "Block type: image_ocr",
                        *_embedded_image_context_lines(embedded_image.metadata),
                        "OCR text:",
                        content,
                    ]
                ),
                source_type="image_ocr",
                source_path=str(parent_path),
                domain=_domain_for_path(parent_path),
                feature=_features_from_text(content),
                metadata={
                    "file_name": parent_path.name,
                    "block_type": "image_ocr",
                    "parent_source_type": embedded_image.parent_source_type,
                    "embedded_path": embedded_image.embedded_path,
                    "embedded_image_index": embedded_image.image_index,
                    "image_width": width,
                    "image_height": height,
                    "image_format": image_format,
                    "ocr_engine": "tesseract",
                    "ocr_languages": IMAGE_OCR_LANGUAGES,
                    **embedded_image.metadata,
                },
                tenant_id=tenant_id,
                bucket_id=bucket_id,
            )
        )
    return documents


def iter_scanned_table_images(raw_data_dir: Path) -> list[EmbeddedImage]:
    images: list[EmbeddedImage] = []
    for path in _image_paths(raw_data_dir):
        images.extend(_scanned_table_images_from_image_file(path))
    return images


def _scanned_table_images_from_image_file(path: Path) -> list[EmbeddedImage]:
    try:
        with Image.open(path) as image:
            rgb_image = image.convert("RGB")
            vertical_lines, horizontal_lines = _detect_table_grid_lines(rgb_image)
            if (
                len(vertical_lines) < SCANNED_TABLE_MIN_GRID_LINES
                or len(horizontal_lines) < SCANNED_TABLE_MIN_GRID_LINES
            ):
                return []

            image_column_index = len(vertical_lines) - 2
            embedded_images: list[EmbeddedImage] = []
            for row_position, row_index in enumerate(range(1, len(horizontal_lines) - 1), start=1):
                row_box = _cell_box(
                    vertical_lines[0],
                    horizontal_lines[row_index],
                    vertical_lines[-1],
                    horizontal_lines[row_index + 1],
                )
                image_cell_box = _cell_box(
                    vertical_lines[image_column_index],
                    horizontal_lines[row_index],
                    vertical_lines[image_column_index + 1],
                    horizontal_lines[row_index + 1],
                )
                if not _cell_has_visual_content(rgb_image, image_cell_box):
                    continue

                crop = rgb_image.crop(image_cell_box)
                content = _encode_image_bytes(crop)
                linked_text = _ocr_image_region(rgb_image.crop(row_box))
                if not linked_text.strip():
                    linked_text = _ocr_image_region(
                        rgb_image.crop(
                            _cell_box(
                                vertical_lines[0],
                                horizontal_lines[row_index],
                                vertical_lines[image_column_index],
                                horizontal_lines[row_index + 1],
                            )
                        )
                    )

                embedded_images.append(
                    EmbeddedImage(
                        parent_path=path,
                        embedded_path=f"scanned-table/table1-row{row_position}-image.png",
                        image_index=row_position,
                        content=content,
                        parent_source_type="scanned_table",
                        metadata={
                            "anchor_type": "scanned_table_cell",
                            "table_index": 0,
                            "table_row_index": row_position,
                            "table_cell_index": image_column_index,
                            "image_cell_bbox": _bbox_metadata(image_cell_box),
                            "table_row_bbox": _bbox_metadata(row_box),
                            "linked_text": linked_text,
                        },
                    )
                )
            return embedded_images
    except Exception as exc:
        warnings.warn(
            f"Scanned table image extraction skipped for {path}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return []


def _detect_table_grid_lines(image: Image.Image) -> tuple[list[int], list[int]]:
    width, height = image.size
    pixels = image.load()

    horizontal_candidates = [
        y
        for y in range(height)
        if _line_pixel_longest_run(pixels, width, y, horizontal=True) / max(1, width)
        >= SCANNED_TABLE_LINE_RATIO
    ]
    vertical_candidates = [
        x
        for x in range(width)
        if _line_pixel_longest_run(pixels, height, x, horizontal=False) / max(1, height)
        >= SCANNED_TABLE_LINE_RATIO
    ]
    return (
        _line_group_centers(vertical_candidates),
        _line_group_centers(horizontal_candidates),
    )


def _line_pixel_longest_run(pixels: Any, length: int, fixed_position: int, *, horizontal: bool) -> int:
    longest_run = 0
    current_run = 0
    for position in range(length):
        pixel = pixels[position, fixed_position] if horizontal else pixels[fixed_position, position]
        if _is_table_line_pixel(pixel):
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    return longest_run


def _is_table_line_pixel(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    is_blue_grid = blue >= 120 and red <= 140 and green <= 170
    is_dark_grid = red <= 80 and green <= 80 and blue <= 80
    return is_blue_grid or is_dark_grid


def _line_group_centers(positions: list[int]) -> list[int]:
    if not positions:
        return []

    groups: list[list[int]] = [[positions[0]]]
    for position in positions[1:]:
        if position - groups[-1][-1] <= 2:
            groups[-1].append(position)
        else:
            groups.append([position])
    return [group[len(group) // 2] for group in groups]


def _cell_box(left: int, top: int, right: int, bottom: int) -> tuple[int, int, int, int]:
    return (
        left + SCANNED_TABLE_CELL_PADDING,
        top + SCANNED_TABLE_CELL_PADDING,
        max(left + SCANNED_TABLE_CELL_PADDING + 1, right - SCANNED_TABLE_CELL_PADDING),
        max(top + SCANNED_TABLE_CELL_PADDING + 1, bottom - SCANNED_TABLE_CELL_PADDING),
    )


def _cell_has_visual_content(image: Image.Image, box: tuple[int, int, int, int]) -> bool:
    crop = image.crop(box)
    width, height = crop.size
    if width <= 0 or height <= 0:
        return False

    rgb_crop = crop.convert("RGB")
    pixels = rgb_crop.load()
    non_background = 0
    for y in range(height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            if _is_foreground_pixel(red, green, blue):
                non_background += 1
    return non_background / max(1, width * height) >= 0.08


def _is_foreground_pixel(red: int, green: int, blue: int) -> bool:
    is_white = red >= 245 and green >= 245 and blue >= 245
    is_light_blue_fill = red >= 190 and green >= 205 and blue >= 220
    is_grid = _is_table_line_pixel((red, green, blue))
    return not (is_white or is_light_blue_fill or is_grid)


def _ocr_image_region(image: Image.Image) -> str:
    if not common._tesseract_available():
        return ""
    return common.ocr_image_text(image)


def _encode_image_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _bbox_metadata(box: tuple[int, int, int, int]) -> dict[str, int]:
    left, top, right, bottom = box
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
    }


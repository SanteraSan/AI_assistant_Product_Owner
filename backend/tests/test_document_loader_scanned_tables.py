from pathlib import Path

from PIL import Image, ImageDraw

from app.services import document_loader
from app.services.document_loader import iter_scanned_table_images


def _build_scanned_table_fixture(path: Path) -> None:
    image = Image.new("RGB", (500, 260), color="white")
    draw = ImageDraw.Draw(image)
    grid_color = (60, 120, 210)
    columns = [20, 160, 300, 420, 480]
    rows = [20, 60, 140, 220]
    for x in columns:
        draw.line((x, rows[0], x, rows[-1]), fill=grid_color, width=2)
    for y in rows:
        draw.line((columns[0], y, columns[-1], y), fill=grid_color, width=2)

    draw.text((30, 75), "PYA TNITSKOE", fill="black")
    draw.text((170, 75), "3500 r", fill="black")
    draw.text((310, 75), "4.1 11", fill="black")
    draw.rectangle((430, 80, 470, 125), fill=(160, 40, 40), outline=(220, 180, 60), width=3)
    image.save(path)


def test_scanned_table_extractor_links_image_cell_to_row_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    image_path = raw_data_dir / "scanned_table.png"
    _build_scanned_table_fixture(image_path)
    monkeypatch.setattr(
        document_loader,
        "_ocr_image_region",
        lambda image: "ПЯТНИЦКОЕ НЕФИЛЬТРОВАННОЕ Цена за кегу 3500 р. 4,1 % алкоголь, 11% плотность",
    )

    embedded_images = iter_scanned_table_images(raw_data_dir)

    assert len(embedded_images) == 1
    embedded_image = embedded_images[0]
    assert embedded_image.parent_path == image_path
    assert embedded_image.parent_source_type == "scanned_table"
    assert embedded_image.embedded_path == "scanned-table/table1-row1-image.png"
    assert embedded_image.metadata["anchor_type"] == "scanned_table_cell"
    assert embedded_image.metadata["table_index"] == 0
    assert embedded_image.metadata["table_row_index"] == 1
    assert embedded_image.metadata["table_cell_index"] == 3
    assert "ПЯТНИЦКОЕ НЕФИЛЬТРОВАННОЕ" in embedded_image.metadata["linked_text"]
    assert "3500" in embedded_image.metadata["linked_text"]

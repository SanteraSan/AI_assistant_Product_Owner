from pathlib import Path

from PIL import Image

from scripts import spike_paddleocr_structure


def test_paddleocr_spike_reports_missing_dependency_without_crashing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "table.png"
    Image.new("RGB", (100, 80), color="white").save(image_path)
    monkeypatch.setattr(
        spike_paddleocr_structure,
        "_missing_dependencies",
        lambda: ["paddleocr", "paddle"],
    )

    result = spike_paddleocr_structure.run_spike(image_path)

    assert result["status"] == "missing_dependency"
    assert result["missing_dependencies"] == ["paddleocr", "paddle"]
    assert "install" in result["install_hint"].lower()

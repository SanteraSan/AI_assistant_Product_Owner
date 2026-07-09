import argparse
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_IMAGE_PATH = Path("/home/santera/Projects/data/raw/scanned_fixtures/scanned-table-products.png")
DEFAULT_OUTPUT_PATH = Path("/home/santera/Projects/research/m583_paddleocr_structure_spike_latest.json")


def main() -> None:
    args = _parse_args()
    image_path = Path(args.image).resolve()
    output_path = Path(args.output).resolve()

    result = run_spike(image_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"status={result['status']}")
    print(f"output={output_path}")
    if result["status"] == "missing_dependency":
        print("missing_dependencies=" + ", ".join(result["missing_dependencies"]))
        print("install_hint=" + result["install_hint"])


def run_spike(image_path: Path) -> dict[str, Any]:
    base_result: dict[str, Any] = {
        "status": "unknown",
        "created_at": datetime.now(UTC).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "image_path": str(image_path),
    }
    if not image_path.exists():
        return {
            **base_result,
            "status": "image_not_found",
            "error": f"Image not found: {image_path}",
        }

    missing_dependencies = _missing_dependencies()
    if missing_dependencies:
        return {
            **base_result,
            "status": "missing_dependency",
            "missing_dependencies": missing_dependencies,
            "install_hint": (
                "Install PaddleOCR in a compatible environment, for example: "
                "python -m pip install paddleocr paddlepaddle"
            ),
            "compatibility_note": (
                "Current backend venv uses Python "
                f"{platform.python_version()}. PaddlePaddle wheels may lag behind new Python releases; "
                "if install fails, create a separate Python 3.10/3.11 spike environment."
            ),
        }

    try:
        engine_name, engine = _build_structure_engine()
        raw_result = _run_structure_engine(engine, image_path)
        return {
            **base_result,
            "status": "completed",
            "engine": engine_name,
            "raw_result_count": len(raw_result) if hasattr(raw_result, "__len__") else None,
            "items": [_summarize_ppstructure_item(item) for item in raw_result],
        }
    except Exception as exc:
        return {
            **base_result,
            "status": "runtime_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _missing_dependencies() -> list[str]:
    missing: list[str] = []
    for module_name in ("paddleocr", "paddle"):
        try:
            __import__(module_name)
        except Exception:
            missing.append(module_name)
    return missing


def _build_structure_engine() -> tuple[str, Any]:
    try:
        from paddleocr import PPStructureV3  # type: ignore

        return "PaddleOCR PPStructureV3", PPStructureV3(
            lang="ru",
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            use_seal_recognition=False,
            use_formula_recognition=False,
            use_chart_recognition=False,
            use_region_detection=False,
        )
    except ImportError:
        from paddleocr import PPStructure  # type: ignore

        return "PaddleOCR PPStructure", _build_legacy_ppstructure_engine(PPStructure)


def _build_legacy_ppstructure_engine(ppstructure_cls: Any) -> Any:
    try:
        return ppstructure_cls(show_log=False, lang="en")
    except TypeError:
        return ppstructure_cls(lang="en")


def _run_structure_engine(engine: Any, image_path: Path) -> Any:
    if callable(engine):
        return engine(str(image_path))
    if hasattr(engine, "predict"):
        return engine.predict(str(image_path))
    msg = f"Unsupported PaddleOCR engine API: {type(engine).__name__}"
    raise TypeError(msg)


def _summarize_ppstructure_item(item: Any) -> dict[str, Any]:
    if hasattr(item, "json"):
        json_payload = getattr(item, "json")
        if isinstance(json_payload, dict):
            return _summarize_ppstructure_json(json_payload)

    if not isinstance(item, dict):
        return {"raw": str(item)}

    result: dict[str, Any] = {
        "type": item.get("type"),
        "bbox": item.get("bbox"),
    }
    if "res" in item:
        result["res_summary"] = _summarize_result_payload(item["res"])
    return result


def _summarize_ppstructure_json(payload: dict[str, Any]) -> dict[str, Any]:
    result_payload = payload.get("res", payload)
    parsing_blocks = result_payload.get("parsing_res_list") or []
    layout_boxes = (
        result_payload.get("layout_det_res", {}).get("boxes")
        if isinstance(result_payload.get("layout_det_res"), dict)
        else None
    )
    return {
        "width": result_payload.get("width"),
        "height": result_payload.get("height"),
        "layout_box_count": len(layout_boxes) if isinstance(layout_boxes, list) else None,
        "blocks": [_summarize_parsing_block(block) for block in parsing_blocks[:20]],
    }


def _summarize_parsing_block(block: Any) -> dict[str, Any]:
    if not isinstance(block, dict):
        return {"raw": str(block)[:1000]}
    return {
        "block_label": block.get("block_label"),
        "block_bbox": block.get("block_bbox"),
        "block_order": block.get("block_order"),
        "block_content": str(block.get("block_content", ""))[:3000],
    }


def _summarize_result_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        return payload[:1000]
    if isinstance(payload, list):
        return [_summarize_result_payload(value) for value in payload[:10]]
    if isinstance(payload, dict):
        return {
            str(key): _summarize_result_payload(value)
            for key, value in list(payload.items())[:20]
        }
    return str(payload)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optional PaddleOCR PP-Structure spike.")
    parser.add_argument(
        "--image",
        default=str(DEFAULT_IMAGE_PATH),
        help="Image path to analyze.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="JSON output path.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()

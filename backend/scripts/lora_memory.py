from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import torch


def capture_vram(label: str) -> dict[str, Any]:
    sample: dict[str, Any] = {"label": label}
    if not torch.cuda.is_available():
        sample["cuda_available"] = False
        return sample

    torch.cuda.synchronize()
    device_index = torch.cuda.current_device()
    free_bytes, total_bytes = torch.cuda.mem_get_info(device_index)
    sample.update(
        {
            "cuda_available": True,
            "device": torch.cuda.get_device_name(device_index),
            "torch_allocated_mb": _bytes_to_mb(torch.cuda.memory_allocated(device_index)),
            "torch_reserved_mb": _bytes_to_mb(torch.cuda.memory_reserved(device_index)),
            "torch_max_allocated_mb": _bytes_to_mb(
                torch.cuda.max_memory_allocated(device_index)
            ),
            "torch_max_reserved_mb": _bytes_to_mb(torch.cuda.max_memory_reserved(device_index)),
            "cuda_free_mb": _bytes_to_mb(free_bytes),
            "cuda_total_mb": _bytes_to_mb(total_bytes),
        }
    )
    sample.update(_nvidia_smi_snapshot())
    return sample


def write_memory_log(path: Path, samples: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "peak": summarize_peak(samples),
                "samples": samples,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def summarize_peak(samples: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_keys = (
        "torch_allocated_mb",
        "torch_reserved_mb",
        "torch_max_allocated_mb",
        "torch_max_reserved_mb",
        "nvidia_smi_memory_used_mb",
    )
    peak: dict[str, Any] = {}
    for key in numeric_keys:
        values = [sample[key] for sample in samples if isinstance(sample.get(key), int)]
        if values:
            peak[key] = max(values)
    return peak


def _nvidia_smi_snapshot() -> dict[str, Any]:
    if shutil.which("nvidia-smi") is None:
        return {}

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception as exc:
        return {"nvidia_smi_error": f"{type(exc).__name__}: {exc}"}

    first_line = result.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) != 4:
        return {"nvidia_smi_raw": first_line}
    return {
        "nvidia_smi_memory_used_mb": int(parts[0]),
        "nvidia_smi_memory_total_mb": int(parts[1]),
        "nvidia_smi_gpu_utilization_percent": int(parts[2]),
        "nvidia_smi_temperature_c": int(parts[3]),
    }


def _bytes_to_mb(value: int) -> int:
    return round(value / 1024 / 1024)

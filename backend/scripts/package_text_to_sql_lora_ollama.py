#!/usr/bin/env python3
"""Package Text-to-SQL PEFT LoRA into an Ollama-usable artifact.

Preferred path (fast): convert adapter → GGUF LoRA + Modelfile
  FROM <base-ollama-tag>
  ADAPTER ./adapter.gguf

Fallback path (heavy): merge PEFT into base HF weights, convert full model to GGUF,
then FROM ./model.gguf.

Example:
  backend/.venv-lora-pack/bin/python scripts/package_text_to_sql_lora_ollama.py \\
    --adapter-dir ../models/text_to_sql_lora/qwen2_5_coder_7b_v5_projection_steps400 \\
    --llama-cpp-dir /tmp/llama.cpp \\
    --ollama-create
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ADAPTER = (
    PROJECT_ROOT / "models/text_to_sql_lora/qwen2_5_coder_7b_v5_projection_steps400"
)
DEFAULT_OUT_DIR = (
    PROJECT_ROOT / "models/text_to_sql_lora/qwen2_5_coder_7b_v5_projection_steps400_ollama"
)
DEFAULT_OLLAMA_TAG = "qwen2_5_coder_7b_v5_projection_steps400"
DEFAULT_BASE_OLLAMA = "qwen2.5-coder:7b"
DEFAULT_BASE_HF = "Qwen/Qwen2.5-Coder-7B-Instruct"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-dir", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--llama-cpp-dir", type=Path, default=Path("/tmp/llama.cpp"))
    parser.add_argument("--base-hf", default=DEFAULT_BASE_HF)
    parser.add_argument("--base-ollama", default=DEFAULT_BASE_OLLAMA)
    parser.add_argument("--ollama-tag", default=DEFAULT_OLLAMA_TAG)
    parser.add_argument(
        "--mode",
        choices=("adapter_gguf", "merge_full"),
        default="adapter_gguf",
        help="adapter_gguf = convert LoRA only; merge_full = merge+full GGUF (slow/heavy).",
    )
    parser.add_argument("--outtype", default="f16", help="GGUF outtype for converters.")
    parser.add_argument(
        "--ollama-create",
        action="store_true",
        help="Run `ollama create` after writing Modelfile.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python used to run llama.cpp converters (needs transformers/gguf/torch).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    adapter_dir = args.adapter_dir.resolve()
    output_dir = args.output_dir.resolve()
    llama_cpp = args.llama_cpp_dir.resolve()

    if not adapter_dir.is_dir():
        raise SystemExit(f"Adapter dir not found: {adapter_dir}")
    if not (adapter_dir / "adapter_config.json").exists():
        raise SystemExit(f"Missing adapter_config.json in {adapter_dir}")
    convert_lora = llama_cpp / "convert_lora_to_gguf.py"
    convert_hf = llama_cpp / "convert_hf_to_gguf.py"
    if not convert_lora.exists():
        raise SystemExit(
            f"Missing {convert_lora}. Clone llama.cpp and pass --llama-cpp-dir."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    adapter_gguf = output_dir / f"{args.ollama_tag}.lora.gguf"
    modelfile = output_dir / "Modelfile"
    manifest_path = output_dir / "package_manifest.json"

    if args.mode == "adapter_gguf":
        convert_cmd = [
            args.python,
            str(convert_lora),
            str(adapter_dir),
            "--outfile",
            str(adapter_gguf),
            "--outtype",
            args.outtype,
        ]
        base_path = Path(args.base_hf)
        if base_path.is_dir():
            convert_cmd.extend(["--base", str(base_path)])
        else:
            convert_cmd.extend(["--base-model-id", args.base_hf])
        _run(convert_cmd, cwd=llama_cpp)
        modelfile.write_text(
            _modelfile_adapter(base_ollama=args.base_ollama, adapter_gguf=adapter_gguf),
            encoding="utf-8",
        )
        artifact = {"mode": "adapter_gguf", "adapter_gguf": str(adapter_gguf)}
    else:
        if not convert_hf.exists():
            raise SystemExit(f"Missing {convert_hf} for merge_full mode.")
        merged_dir = output_dir / "merged_hf"
        model_gguf = output_dir / f"{args.ollama_tag}.gguf"
        _merge_adapter(
            base_hf=args.base_hf,
            adapter_dir=adapter_dir,
            merged_dir=merged_dir,
        )
        _run(
            [
                args.python,
                str(convert_hf),
                str(merged_dir),
                "--outfile",
                str(model_gguf),
                "--outtype",
                args.outtype,
            ],
            cwd=llama_cpp,
        )
        modelfile.write_text(
            _modelfile_full(model_gguf=model_gguf),
            encoding="utf-8",
        )
        artifact = {
            "mode": "merge_full",
            "merged_hf": str(merged_dir),
            "model_gguf": str(model_gguf),
        }

    manifest = {
        "ollama_tag": args.ollama_tag,
        "base_ollama": args.base_ollama,
        "base_hf": args.base_hf,
        "adapter_dir": str(adapter_dir),
        "modelfile": str(modelfile),
        **artifact,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))

    if args.ollama_create:
        _run(["ollama", "create", args.ollama_tag, "-f", str(modelfile)])
        print(f"Created Ollama model: {args.ollama_tag}")

    return 0


def _merge_adapter(*, base_hf: str, adapter_dir: Path, merged_dir: Path) -> None:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if merged_dir.exists():
        shutil.rmtree(merged_dir)
    merged_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading base model on CPU: {base_hf}")
    base = AutoModelForCausalLM.from_pretrained(
        base_hf,
        torch_dtype=torch.float16,
        device_map="cpu",
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(base_hf, trust_remote_code=True)
    print(f"Loading adapter: {adapter_dir}")
    model = PeftModel.from_pretrained(base, str(adapter_dir))
    print("Merging adapter weights...")
    merged = model.merge_and_unload()
    print(f"Saving merged HF model to {merged_dir}")
    merged.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)


def _modelfile_adapter(*, base_ollama: str, adapter_gguf: Path) -> str:
    return f"""FROM {base_ollama}
ADAPTER {adapter_gguf}

PARAMETER temperature 0
PARAMETER num_ctx 8192
"""


def _modelfile_full(*, model_gguf: Path) -> str:
    return f"""FROM {model_gguf}

PARAMETER temperature 0
PARAMETER num_ctx 8192
"""


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, cwd=cwd)


if __name__ == "__main__":
    raise SystemExit(main())

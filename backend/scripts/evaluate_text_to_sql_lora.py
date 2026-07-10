from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import torch
from peft import PeftModel
from sqlglot import exp, parse_one
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from app.services.sql_validator import extract_sql_from_response, validate_read_only_sql  # noqa: E402
from lora_memory import capture_vram, summarize_peak, write_memory_log  # noqa: E402


DEFAULT_DATA_PATH = PROJECT_ROOT / "data/text_to_sql/v1/test.jsonl"
DEFAULT_ADAPTER_DIR = PROJECT_ROOT / "models/text_to_sql_lora/qwen2_5_coder_7b_v1_smoke"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "research/text_to_sql_lora_eval_latest.json"


@dataclass(frozen=True)
class LoraEvalResult:
    example_id: str
    intent_id: str | None
    latency_ms: int
    instruction: str
    expected_sql: str
    response: str
    extracted_sql: str
    validation_valid: bool
    validation_error: str | None
    tables: list[str]
    required_tables_present: bool
    required_terms_present: bool
    expected_projection: list[str]
    generated_projection: list[str]
    projection_exact_match: bool | None
    normalized_exact_match: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a local Text-to-SQL LoRA adapter.")
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-Coder-7B-Instruct")
    parser.add_argument("--adapter-dir", default=str(DEFAULT_ADAPTER_DIR))
    parser.add_argument("--data-path", default=str(DEFAULT_DATA_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--memory-log", default=None)
    parser.add_argument("--base-only", action="store_true")
    parser.add_argument("--no-4bit", action="store_true")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def build_prompt(example: dict[str, Any]) -> str:
    return f"""<|im_start|>system
Ты генерируешь безопасный PostgreSQL SQL для аналитики.
Верни только один read-only SELECT или WITH ... SELECT statement без markdown и объяснений.<|im_end|>
<|im_start|>user
{example["input"]}

Вопрос:
{example["instruction"]}<|im_end|>
<|im_start|>assistant
"""


def load_model(
    *,
    model_name: str,
    adapter_dir: Path,
    use_4bit: bool,
    base_only: bool,
):
    quantization_config = None
    if use_4bit:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )

    base_model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=quantization_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    model = base_model if base_only else PeftModel.from_pretrained(base_model, str(adapter_dir))
    model.eval()
    return model


def load_tokenizer(model_name: str, adapter_dir: Path):
    tokenizer = AutoTokenizer.from_pretrained(
        str(adapter_dir) if (adapter_dir / "tokenizer_config.json").exists() else model_name,
        trust_remote_code=True,
        use_fast=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.truncation_side = "left"
    return tokenizer


def generate_sql(
    *,
    model,
    tokenizer,
    prompt: str,
    max_length: int,
    max_new_tokens: int,
) -> tuple[str, int]:
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=max_length,
    ).to(model.device)
    started_at = perf_counter()
    with torch.inference_mode():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    latency_ms = int((perf_counter() - started_at) * 1000)
    generated_ids = output_ids[0][inputs["input_ids"].shape[-1] :]
    return tokenizer.decode(generated_ids, skip_special_tokens=True).strip(), latency_ms


def normalize(sql: str, allowed_tables: set[str]) -> str | None:
    validation = validate_read_only_sql(sql, allowed_tables=allowed_tables)
    return validation.normalized_sql if validation.valid else None


def evaluate_example(
    *,
    example: dict[str, Any],
    response: str,
    latency_ms: int,
    allowed_tables: set[str],
) -> LoraEvalResult:
    extracted_sql = extract_sql_from_response(response)
    validation = validate_read_only_sql(extracted_sql, allowed_tables=allowed_tables)
    required_tables = set(example.get("metadata", {}).get("required_tables", []))
    required_terms = tuple(example.get("metadata", {}).get("required_terms", []))
    expected_projection = list(example.get("metadata", {}).get("required_projection", []))
    expected_normalized = normalize(example["output"], allowed_tables)
    generated_normalized = validation.normalized_sql if validation.valid else None
    sql_texts_for_term_checks = (
        extracted_sql.lower(),
        (generated_normalized or "").lower(),
    )
    generated_projection = extract_projection(generated_normalized or extracted_sql)

    return LoraEvalResult(
        example_id=example["id"],
        intent_id=example.get("metadata", {}).get("intent_id"),
        latency_ms=latency_ms,
        instruction=example["instruction"],
        expected_sql=example["output"],
        response=response,
        extracted_sql=extracted_sql,
        validation_valid=validation.valid,
        validation_error=validation.error,
        tables=validation.tables,
        required_tables_present=required_tables.issubset(set(validation.tables)),
        required_terms_present=all(
            any(term.lower() in sql_text for sql_text in sql_texts_for_term_checks)
            for term in required_terms
        ),
        expected_projection=expected_projection,
        generated_projection=generated_projection,
        projection_exact_match=(
            None
            if not expected_projection
            else [item.lower() for item in generated_projection]
            == [item.lower() for item in expected_projection]
        ),
        normalized_exact_match=(
            generated_normalized is not None
            and expected_normalized is not None
            and generated_normalized.lower() == expected_normalized.lower()
        ),
    )


def summarize(results: list[LoraEvalResult]) -> dict[str, Any]:
    total = len(results)
    projection_results = [
        result for result in results if result.projection_exact_match is not None
    ]
    return {
        "total": total,
        "valid_sql": sum(result.validation_valid for result in results),
        "required_tables_present": sum(result.required_tables_present for result in results),
        "required_terms_present": sum(result.required_terms_present for result in results),
        "projection_examples": len(projection_results),
        "projection_exact_match": sum(
            result.projection_exact_match is True for result in projection_results
        ),
        "normalized_exact_match": sum(result.normalized_exact_match for result in results),
        "avg_latency_ms": round(sum(result.latency_ms for result in results) / total)
        if total
        else 0,
    }


def extract_projection(sql: str) -> list[str]:
    try:
        parsed = parse_one(sql, read="postgres")
    except Exception:
        return []
    if not isinstance(parsed, exp.Select):
        return []

    projection: list[str] = []
    for expression in parsed.expressions:
        alias = expression.alias
        if alias:
            projection.append(alias)
            continue
        if isinstance(expression, exp.Column):
            projection.append(expression.name)
            continue
        if isinstance(expression, exp.Star):
            projection.append("*")
            continue
        projection.append(expression.sql(dialect="postgres").lower())
    return projection


def summarize_by_intent(results: list[LoraEvalResult]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for intent_id in sorted({result.intent_id or "unknown" for result in results}):
        intent_results = [
            result for result in results if (result.intent_id or "unknown") == intent_id
        ]
        summary[intent_id] = summarize(intent_results)
    return summary


def main() -> None:
    args = parse_args()
    adapter_dir = Path(args.adapter_dir)
    output_path = Path(args.output)
    memory_log_path = (
        Path(args.memory_log)
        if args.memory_log
        else output_path.with_suffix(".memory.json")
    )
    memory_samples: list[dict[str, Any]] = [capture_vram("start")]
    write_memory_log(memory_log_path, memory_samples)
    examples = read_jsonl(Path(args.data_path))
    allowed_tables = {
        "chat_messages",
        "chat_sessions",
        "conversation_summaries",
        "evaluation_results",
        "evaluation_runs",
        "rag_request_logs",
        "rag_source_logs",
    }

    tokenizer = load_tokenizer(args.model_name, adapter_dir)
    model = load_model(
        model_name=args.model_name,
        adapter_dir=adapter_dir,
        use_4bit=not args.no_4bit,
        base_only=args.base_only,
    )
    memory_samples.append(capture_vram("after_model_load"))
    write_memory_log(memory_log_path, memory_samples)

    results: list[LoraEvalResult] = []
    for example in examples:
        response, latency_ms = generate_sql(
            model=model,
            tokenizer=tokenizer,
            prompt=build_prompt(example),
            max_length=args.max_length,
            max_new_tokens=args.max_new_tokens,
        )
        result = evaluate_example(
            example=example,
            response=response,
            latency_ms=latency_ms,
            allowed_tables=allowed_tables,
        )
        results.append(result)
        memory_samples.append(capture_vram(f"after_example_{result.example_id}"))
        write_memory_log(memory_log_path, memory_samples)
        print(
            "ok "
            f"example={result.example_id} "
            f"valid={result.validation_valid} "
            f"tables={result.required_tables_present} "
            f"terms={result.required_terms_present} "
            f"projection={result.projection_exact_match} "
            f"exact={result.normalized_exact_match} "
            f"latency_ms={result.latency_ms}"
        )

    payload = {
        "model_name": args.model_name,
        "adapter_dir": None if args.base_only else str(adapter_dir),
        "base_only": args.base_only,
        "data_path": str(args.data_path),
        "summary": summarize(results),
        "summary_by_intent": summarize_by_intent(results),
        "memory_log": str(memory_log_path),
        "memory_peak": summarize_peak(memory_samples),
        "results": [asdict(result) for result in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

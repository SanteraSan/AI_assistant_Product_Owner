#!/usr/bin/env python3
"""Zero-shot class labels on the frozen v1 holdout and an equal stratum.

Rules are ``lexicon_rule_class``. QLoRA does not run. Postgres, Qdrant, and
``index_in_rag`` are untouched. From the repository root, with the backend
interpreter (not ``.venv-lora``):

    python backend/scripts/eval_feedback_zero_shot.py --model qwen3.8:latest
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.services.feedback_rules import lexicon_rule_class  # noqa: E402
from app.services.feedback_zero_shot_score import (  # noqa: E402
    CLASS_ORDER,
    CONTEST_REASON,
    STRATUM_PER_CLASS,
    STRATUM_SEED,
    decide_qlora_gate,
    holdout_agreement,
    parse_feedback_class_response,
    score_predictions,
    select_stratified_rows,
)
from app.services.ollama_client import OllamaClient  # noqa: E402

_V1_DIR = REPO_ROOT / "data" / "feedback" / "v1"
_HOLDOUT_PATH = _V1_DIR / "holdout.jsonl"
_CLEANED_PATH = _V1_DIR / "cleaned.jsonl"
_MANIFEST_PATH = _V1_DIR / "manifest.json"
_PROMPT_FILE = REPO_ROOT / "research" / "prompts" / "feedback_zero_shot_class.txt"
_OUTPUT_PATH = REPO_ROOT / "research" / "feedback_zero_shot_eval_latest.json"
_PROMPT_PATH = "research/prompts/feedback_zero_shot_class.txt"
_HOLDOUT_REL = "data/feedback/v1/holdout.jsonl"
_CLEANED_REL = "data/feedback/v1/cleaned.jsonl"
_REQUIRED_CHAT_MODEL = "qwen3.8:latest"
_TEMPERATURE = 0
_TOP_P = 1
_NUM_CTX = 4096
_NUM_PREDICT = 128
_SEED = 7
_KEEP_ALIVE = "10m"
_RESPONSE_FORMAT = "json"
_REPEATS = 1
_TIMEOUT_SECONDS = 600.0
_CALLS = 52
_HOLDOUT_ROWS = 20
_REASON_ORDER = ("lexicon_noise", "lexicon_churn", "keep_generator")
_MODEL_FLAG_ERROR = (
    "Flag must be --model qwen3.8:latest. "
    "qwen3.5:9b is a different run. The product default model is not used."
)
_RULES_EXPLANATION = (
    "lexicon_rule_class keeps fallback_class unless the normalized text is in the noise "
    "or churn lexicon. On holdout the fallback is the manual generator_class. "
    "This is not an independent bug-versus-feature classifier."
)
_KEEP_GENERATOR_NOTE = (
    "keep_generator на holdout не открывает ворота: правило оставило ручную метку, "
    "потому что нормализованный текст не попал в лексикон шума и коротких сигналов."
)


class _ProtocolError(Exception):
    """Holdout bytes, the manifest, or the stratum cannot be trusted."""


@dataclass(frozen=True)
class _CallRow:
    split: str
    row_id: str
    line_no: int
    corpus_id: str | None
    scenario_id: str | None
    text: str
    source_file: str | None
    source_line: int | None
    gold_class: str
    rule_class: str
    rule_reason: str


@dataclass(frozen=True)
class _Prepared:
    calls: tuple[_CallRow, ...]
    prompt: str
    prompt_sha256: str
    holdout_sha256: str
    sha256_matches_manifest: bool
    class_support: dict[str, int]
    rule_reason: dict[str, int]
    mismatches: tuple[dict[str, Any], ...]
    corpus_ids: tuple[str, ...]


def assert_chat_model(model: str) -> None:
    """Accept only the stage-7 chat tag. Product defaults are not consulted."""

    if model.strip() != _REQUIRED_CHAT_MODEL:
        raise SystemExit(2)


class _ModelArgumentParser(argparse.ArgumentParser):
    """Keep argparse from printing its own usage. ``main`` prints the flag sentence."""

    def error(self, _message: str) -> None:
        raise SystemExit(2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = _ModelArgumentParser(
        description="Zero-shot feedback class labels for the frozen holdout and an equal stratum.",
    )
    parser.add_argument("--model", required=True, help="Chat model. Must be qwen3.8:latest.")
    return parser.parse_args(None if argv is None else list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        if exc.code in (None, 0):
            return 0
        print(_MODEL_FLAG_ERROR, file=sys.stderr)
        return 2
    try:
        assert_chat_model(str(args.model))
    except SystemExit:
        print(_MODEL_FLAG_ERROR, file=sys.stderr)
        return 2
    model = str(args.model).strip()
    try:
        prepared = _prepare()
    except _ProtocolError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        return asyncio.run(_evaluate(prepared, model=model))
    except Exception as exc:
        print(f"feedback zero-shot eval failed: {exc}", file=sys.stderr)
        return 1


def _prepare() -> _Prepared:
    try:
        return _load_protocol()
    except _ProtocolError:
        raise
    except (OSError, ValueError, json.JSONDecodeError, UnicodeError) as exc:
        raise _ProtocolError(str(exc)) from exc


def _load_protocol() -> _Prepared:
    manifest = _read_json(_MANIFEST_PATH)
    expected_sha = manifest.get("holdout_sha256")
    if not isinstance(expected_sha, str) or not expected_sha:
        raise _ProtocolError("manifest holdout_sha256 is missing")
    holdout_bytes = _HOLDOUT_PATH.read_bytes()
    holdout_sha = hashlib.sha256(holdout_bytes).hexdigest()
    sha_matches = holdout_sha == expected_sha
    if not sha_matches:
        raise _ProtocolError(
            f"holdout sha256 {holdout_sha} does not match manifest holdout_sha256"
        )
    holdout = _holdout_rows(holdout_bytes)
    if len(holdout) != _HOLDOUT_ROWS:
        raise _ProtocolError(f"holdout has {len(holdout)} non-empty rows, expected {_HOLDOUT_ROWS}")
    cleaned_rows, cleaned_lines = _read_jsonl(_CLEANED_PATH)
    selected = select_stratified_rows(
        cleaned_rows,
        holdout_texts=[row.text for row in holdout],
        per_class=STRATUM_PER_CLASS,
        seed=STRATUM_SEED,
    )
    if selected.shortfall or len(selected.rows) != STRATUM_PER_CLASS * len(CLASS_ORDER):
        raise _ProtocolError(
            "stratified slice is short of 8 rows per class: "
            f"rows={len(selected.rows)} shortfall={selected.shortfall}. Quota stays 8."
        )
    stratified_calls: list[_CallRow] = []
    for row in selected.rows:
        line_no = cleaned_lines.get(row.corpus_id)
        if line_no is None:
            raise _ProtocolError(f"{row.corpus_id} has no line in cleaned.jsonl")
        stratified_calls.append(_call_from_stratum(row, line_no=line_no))
    stratified = tuple(stratified_calls)
    expected_classes = [name for name in CLASS_ORDER for _index in range(STRATUM_PER_CLASS)]
    if [row.gold_class for row in stratified] != expected_classes:
        raise _ProtocolError("stratified calls are not in class order")
    prompt_bytes = _PROMPT_FILE.read_bytes()
    prompt = prompt_bytes.decode("utf-8")
    if prompt.count("{text}") != 1:
        raise _ProtocolError("zero-shot prompt must contain exactly one {text}")
    if prompt.count("Обращение:") != 1:
        raise _ProtocolError("zero-shot prompt must contain exactly one Обращение:")
    calls = holdout + stratified
    if len(calls) != _CALLS:
        raise _ProtocolError(f"expected {_CALLS} calls, got {len(calls)}")
    return _Prepared(
        calls=calls,
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt_bytes).hexdigest(),
        holdout_sha256=holdout_sha,
        sha256_matches_manifest=sha_matches,
        class_support=_class_support(holdout),
        rule_reason=_reason_counts([row.rule_reason for row in holdout]),
        mismatches=_mismatches(holdout),
        corpus_ids=tuple(row.corpus_id for row in stratified if row.corpus_id is not None),
    )


def _holdout_rows(holdout_bytes: bytes) -> tuple[_CallRow, ...]:
    text = holdout_bytes.decode("utf-8")
    rows: list[_CallRow] = []
    ordinal = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        ordinal += 1
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise _ProtocolError(f"holdout:{line_no} is not an object")
        rows.append(_call_from_payload(payload, split="holdout", row_id=f"holdout:{ordinal}", line_no=line_no))
    return tuple(rows)


def _call_from_payload(
    payload: Mapping[str, Any],
    *,
    split: str,
    row_id: str,
    line_no: int,
    source_file: str | None = None,
    source_line: int | None = None,
    corpus_id: str | None = None,
) -> _CallRow:
    body = payload.get("text")
    gold = payload.get("generator_class")
    if not isinstance(body, str) or not isinstance(gold, str):
        raise _ProtocolError(f"{row_id} is missing text or generator_class")
    scenario_id = payload.get("scenario_id")
    if scenario_id is not None and not isinstance(scenario_id, str):
        raise _ProtocolError(f"{row_id} scenario_id is not a string")
    file_corpus_id = payload.get("corpus_id")
    if corpus_id is None and isinstance(file_corpus_id, str):
        corpus_id = file_corpus_id
    rule_class, rule_reason = lexicon_rule_class(body, fallback_class=gold)
    return _CallRow(
        split=split,
        row_id=row_id,
        line_no=line_no,
        corpus_id=corpus_id,
        scenario_id=scenario_id,
        text=body,
        source_file=source_file,
        source_line=source_line,
        gold_class=gold,
        rule_class=rule_class,
        rule_reason=rule_reason,
    )


def _call_from_stratum(row: Any, *, line_no: int) -> _CallRow:
    rule_class, rule_reason = lexicon_rule_class(row.text, fallback_class=row.generator_class)
    return _CallRow(
        split="stratified",
        row_id=row.corpus_id,
        line_no=line_no,
        corpus_id=row.corpus_id,
        scenario_id=row.scenario_id,
        text=row.text,
        source_file=row.source_file,
        source_line=row.source_line,
        gold_class=row.generator_class,
        rule_class=rule_class,
        rule_reason=rule_reason,
    )


async def _evaluate(prepared: _Prepared, *, model: str) -> int:
    settings = get_settings()
    ollama_base_url = settings.ollama_base_url
    client = OllamaClient(base_url=ollama_base_url, timeout_seconds=_TIMEOUT_SECONDS)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
            classified, ps_first, ps_last = await _classify(
                client,
                http,
                prepared,
                model=model,
                ollama_base_url=ollama_base_url,
            )
        document = _document(
            prepared,
            classified,
            model=model,
            ollama_ps_first=ps_first,
            ollama_ps_last=ps_last,
        )
        _write_json(_OUTPUT_PATH, document)
        gate = document["qlora_gate"]
        print(
            f"wrote {_OUTPUT_PATH} qlora_gate.open={gate['open']} "
            f"mismatch_count={gate['mismatch_count']}"
        )
        return 0
    finally:
        await client.aclose()


async def _classify(
    client: OllamaClient,
    http: httpx.AsyncClient,
    prepared: _Prepared,
    *,
    model: str,
    ollama_base_url: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    ps_first: dict[str, Any] | None = None
    ps_last: dict[str, Any] | None = None
    total = len(prepared.calls)
    for index, row in enumerate(prepared.calls):
        prompt = prepared.prompt.replace("{text}", row.text, 1)
        started = time.perf_counter()
        generated = await client.generate(
            model,
            prompt,
            keep_alive=_KEEP_ALIVE,
            options={
                "temperature": _TEMPERATURE,
                "top_p": _TOP_P,
                "num_ctx": _NUM_CTX,
                "num_predict": _NUM_PREDICT,
                "seed": _SEED,
            },
            think=False,
            response_format=_RESPONSE_FORMAT,
        )
        wall_ms = int((time.perf_counter() - started) * 1000)
        if not isinstance(generated, dict):
            raise RuntimeError("Ollama generate response is not an object")
        if index == 0:
            ps_first = await _read_ps(http, ollama_base_url, model)
        if index == total - 1:
            ps_last = await _read_ps(http, ollama_base_url, model)
        raw = _response_text(generated)
        parsed = parse_feedback_class_response(raw)
        predicted = parsed.predicted_class if parsed.predicted_class is not None else "None"
        print(
            f"{row.split} {row.row_id} gold={row.gold_class} rule={row.rule_class} "
            f"predicted={predicted} wall_ms={wall_ms}",
            flush=True,
        )
        classified.append(_row_payload(row, parsed.predicted_class, parsed.parse_error, raw, generated, wall_ms))
    if ps_first is None or ps_last is None:
        raise RuntimeError("ollama /api/ps was not read")
    return classified, ps_first, ps_last


def _row_payload(
    row: _CallRow,
    predicted_class: str | None,
    parse_error: str | None,
    raw_response: str,
    generated: Mapping[str, Any],
    wall_ms: int,
) -> dict[str, Any]:
    return {
        "split": row.split,
        "row_id": row.row_id,
        "line_no": row.line_no,
        "corpus_id": row.corpus_id,
        "scenario_id": row.scenario_id,
        "text": row.text,
        "source_file": row.source_file,
        "source_line": row.source_line,
        "gold_class": row.gold_class,
        "rule_class": row.rule_class,
        "rule_reason": row.rule_reason,
        "predicted_class": predicted_class,
        "parse_error": parse_error,
        "raw_response": raw_response,
        "latency_ms": _ns_to_ms(generated, "total_duration"),
        "latency_ms_wall": wall_ms,
        "eval_duration_ms": _ns_to_ms(generated, "eval_duration"),
        "load_duration_ms": _ns_to_ms(generated, "load_duration"),
    }


def _document(
    prepared: _Prepared,
    classified: Sequence[Mapping[str, Any]],
    *,
    model: str,
    ollama_ps_first: Mapping[str, Any],
    ollama_ps_last: Mapping[str, Any],
) -> dict[str, Any]:
    holdout_rows = [row for row in classified if row["split"] == "holdout"]
    stratum_rows = [row for row in classified if row["split"] == "stratified"]
    if len(holdout_rows) != _HOLDOUT_ROWS or len(stratum_rows) != STRATUM_PER_CLASS * len(CLASS_ORDER):
        raise RuntimeError("classified rows are not 20 holdout plus 32 stratum")
    holdout_golds = [str(row["gold_class"]) for row in holdout_rows]
    stratum_golds = [str(row["gold_class"]) for row in stratum_rows]
    holdout_rules = [str(row["rule_class"]) for row in holdout_rows]
    stratum_rules = [str(row["rule_class"]) for row in stratum_rows]
    holdout_predicted = [_predicted(row) for row in holdout_rows]
    stratum_predicted = [_predicted(row) for row in stratum_rows]
    agreement = holdout_agreement(holdout_golds, holdout_rules, holdout_predicted)
    agreement_total = (
        agreement["both_correct"]
        + agreement["rules_only"]
        + agreement["zero_shot_only"]
        + agreement["both_wrong"]
    )
    if agreement_total != _HOLDOUT_ROWS:
        raise RuntimeError(f"holdout agreement sums to {agreement_total}, expected {_HOLDOUT_ROWS}")
    gate = decide_qlora_gate(len(prepared.mismatches))
    wall_values = [int(row["latency_ms_wall"]) for row in classified]
    wall_sum = sum(wall_values)
    gate_payload = asdict(gate)
    gate_payload["mismatches"] = list(prepared.mismatches)
    return {
        "stage": 7,
        "model": model,
        "model_source": "cli_flag",
        "product_default_not_used": True,
        "embedding_model": None,
        "qdrant_used": False,
        "postgres_used": False,
        "index_in_rag_unchanged": True,
        "prompt_path": _PROMPT_PATH,
        "prompt_sha256": prepared.prompt_sha256,
        "protocol": {
            "temperature": _TEMPERATURE,
            "top_p": _TOP_P,
            "num_ctx": _NUM_CTX,
            "num_predict": _NUM_PREDICT,
            "seed": _SEED,
            "think": False,
            "response_format": _RESPONSE_FORMAT,
            "repeats": _REPEATS,
            "timeout_seconds": 600,
            "keep_alive": _KEEP_ALIVE,
        },
        "holdout": {
            "path": _HOLDOUT_REL,
            "rows": _HOLDOUT_ROWS,
            "sha256": prepared.holdout_sha256,
            "sha256_matches_manifest": prepared.sha256_matches_manifest,
            "class_support": prepared.class_support,
            "rule_reason": prepared.rule_reason,
            "keep_generator_note": _KEEP_GENERATOR_NOTE,
        },
        "stratified": {
            "path": _CLEANED_REL,
            "allocation": "equal",
            "per_class": STRATUM_PER_CLASS,
            "seed": STRATUM_SEED,
            "rows": len(stratum_rows),
            "corpus_ids": list(prepared.corpus_ids),
            "contest_against_generator_class": False,
            "contest_reason": CONTEST_REASON,
        },
        "qlora_gate": gate_payload,
        "rules_explanation": _RULES_EXPLANATION,
        "scores": {
            "holdout": {
                "rules": asdict(score_predictions(holdout_golds, holdout_rules)),
                "zero_shot": asdict(score_predictions(holdout_golds, holdout_predicted)),
            },
            "stratified": {
                "rules": asdict(score_predictions(stratum_golds, stratum_rules)),
                "zero_shot": asdict(score_predictions(stratum_golds, stratum_predicted)),
            },
        },
        "agreement": {"holdout": agreement},
        "ollama_ps_first": dict(ollama_ps_first),
        "ollama_ps_last": dict(ollama_ps_last),
        "latency_ms_wall_sum": wall_sum,
        "latency_ms_wall_mean": wall_sum / len(classified),
        "calls": len(classified),
        "rows": [dict(row) for row in classified],
    }


def _predicted(row: Mapping[str, Any]) -> str | None:
    value = row.get("predicted_class")
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _class_support(rows: Sequence[_CallRow]) -> dict[str, int]:
    support = {name: 0 for name in CLASS_ORDER}
    for row in rows:
        if row.gold_class not in support:
            raise _ProtocolError(f"{row.row_id} class {row.gold_class!r} is outside the four classes")
        support[row.gold_class] += 1
    return support


def _reason_counts(reasons: Sequence[str]) -> dict[str, int]:
    counts = {name: 0 for name in _REASON_ORDER}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _mismatches(rows: Sequence[_CallRow]) -> tuple[dict[str, Any], ...]:
    found: list[dict[str, Any]] = []
    for row in rows:
        if row.rule_class == row.gold_class:
            continue
        found.append(
            {
                "line_no": row.line_no,
                "row_id": row.row_id,
                "generator_class": row.gold_class,
                "rule_class": row.rule_class,
                "text_preview": row.text[:80],
            }
        )
    return tuple(found)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not an object")
    return payload


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    lines: dict[str, int] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}:{line_no} is not an object")
        corpus_id = payload.get("corpus_id")
        if isinstance(corpus_id, str) and corpus_id not in lines:
            lines[corpus_id] = line_no
        rows.append(payload)
    return rows, lines


def _response_text(payload: Mapping[str, Any]) -> str:
    value = payload.get("response")
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _ns_to_ms(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, int):
        return value // 1_000_000
    return int(value / 1_000_000)


def _empty_ps(model: str) -> dict[str, Any]:
    return {
        "name": model,
        "size": 0,
        "size_vram": 0,
        "gpu_share": None,
        "cpu_share": None,
        "context_length": None,
    }


async def _read_ps(http: httpx.AsyncClient, base_url: str, model: str) -> dict[str, Any]:
    try:
        response = await http.get(f"{base_url.rstrip('/')}/api/ps")
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"ollama /api/ps unavailable: {exc}", file=sys.stderr)
        return _empty_ps(model)
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return _empty_ps(model)
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        model_name = entry.get("model")
        if name != model and model_name != model:
            continue
        size = _json_int(entry.get("size"))
        size_vram = _json_int(entry.get("size_vram"))
        gpu_share = None
        cpu_share = None
        if size:
            gpu_share = size_vram / size
            cpu_share = 1 - gpu_share
        reported_name = name if isinstance(name, str) and name else model
        return {
            "name": reported_name,
            "size": size,
            "size_vram": size_vram,
            "gpu_share": gpu_share,
            "cpu_share": cpu_share,
            "context_length": _optional_int(entry.get("context_length")),
        }
    return _empty_ps(model)


def _json_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(partial, path)


if __name__ == "__main__":
    raise SystemExit(main())

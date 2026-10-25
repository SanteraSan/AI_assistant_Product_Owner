#!/usr/bin/env python3
"""Measure H0 against H1 on the frozen v1 feedback summary.

The corpus files are read-only. Postgres, the indexing worker, and the product
Qdrant collection are not used. Chat and embedding model names come from CLI
flags. Run this only after the stage tests are green:

    python backend/scripts/eval_feedback_summary.py \
        --model qwen3.8:latest \
        --embedding-model nomic-embed-text
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.clients.qdrant_store import QdrantStore, _payload_filter  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.models.chat import SourceChunk  # noqa: E402
from app.services.feedback_eval_index import (  # noqa: E402
    EVAL_BUCKET_ID,
    EVAL_COLLECTION_NAME,
    EVAL_KEEP_ALIVE,
    EVAL_NUM_CTX,
    EVAL_REPEATS,
    EVAL_TEMPERATURE,
    EVAL_TENANT_ID,
    EVAL_TOP_K,
    EVAL_TOP_P,
    EXPECTED_CORPUS_ROWS,
    EXPECTED_VECTOR_SIZE,
    REQUIRED_CHAT_MODEL,
    REQUIRED_EMBEDDING_MODEL,
    assert_eval_collection_is_not_product,
    build_eval_point_payload,
    eval_point_id,
    retrieve_arm,
    retrieved_source_from_chunk,
)
from app.services.feedback_rules import SCENARIO_IDS  # noqa: E402
from app.services.feedback_summary_score import (  # noqa: E402
    GoldQuestion,
    HoldoutGateResult,
    JudgeScore,
    MarkerScore,
    RetrievedSource,
    accept_h1,
    assert_gold_matches_manifest,
    check_holdout_gate,
    h2_note,
    judge_diverged,
    load_summary_gold,
    mean_metric,
    parse_judge_payload,
    score_markers,
)
from app.services.ollama_client import OllamaClient  # noqa: E402

_V1_DIR = REPO_ROOT / "data" / "feedback" / "v1"
_GOLD_PATH = _V1_DIR / "summary_gold.json"
_MANIFEST_PATH = _V1_DIR / "manifest.json"
_CLEANED_PATH = _V1_DIR / "cleaned.jsonl"
_HOLDOUT_PATH = _V1_DIR / "holdout.jsonl"
_USER_PROMPT_PATH = REPO_ROOT / "research" / "prompts" / "feedback_summary_user.txt"
_JUDGE_PROMPT_PATH = REPO_ROOT / "research" / "prompts" / "feedback_summary_judge.txt"
_OUTPUT_PATH = REPO_ROOT / "research" / "feedback_summary_eval_latest.json"
_PROMPT_PATH = "research/prompts/feedback_summary_user.txt"
_JUDGE_PATH = "research/prompts/feedback_summary_judge.txt"
_CLASS_NAMES = ("noise", "churn_signal", "bug", "feature")
_GENERATE_TIMEOUT_SECONDS = 600.0
_JUDGE_TEMPERATURE = 0.0
_UPSERT_BATCH = 64
_PLACEHOLDER_RE = re.compile(r"\{(question|context|answer|must_not|expected_scenario_ids)\}")
_POSTGRES_REASON = (
    "Seed этапа 2 в рабочую Postgres не выполнялся. "
    "Знаменатель — counts манифеста, проверенные scroll коллекции feedback_eval_v1. "
    "Продуктовый бакет не засевается."
)
_ARM_ORDER: tuple[Literal["H0", "H1"], ...] = ("H0", "H1")
_MODEL_FLAG_ERROR = (
    "Flags must be --model qwen3.8:latest and --embedding-model nomic-embed-text. "
    "The product default model is not used."
)


class _ProtocolError(Exception):
    """Gold, manifest, cleaned rows, or the holdout gate cannot be trusted."""


@dataclass(frozen=True)
class _Prepared:
    questions: tuple[GoldQuestion, GoldQuestion]
    manifest: dict[str, Any]
    rows: list[dict[str, Any]]
    gate: HoldoutGateResult
    user_prompt: str
    judge_prompt: str


@dataclass
class _Run:
    arm: str
    question: GoldQuestion
    repeat: int
    answer: str
    latency_ms: int
    eval_duration_ms: int
    load_duration_ms: int
    latency_ms_wall: int
    ollama_ps: dict[str, Any]
    sources: list[RetrievedSource]
    scores: list[float | None]
    markers: MarkerScore
    judge: JudgeScore | None
    diverged: bool | None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure frozen feedback summary retrieval for H0 and H1.",
    )
    parser.add_argument("--model", required=True, help="Chat model. Must be qwen3.8:latest.")
    parser.add_argument(
        "--embedding-model",
        required=True,
        help="Embedding model. Must be nomic-embed-text.",
    )
    return parser.parse_args(None if argv is None else list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        if exc.code in (None, 0):
            return 0
        print(_MODEL_FLAG_ERROR, file=sys.stderr)
        return 2
    chat_model = str(args.model).strip()
    embedding_model = str(args.embedding_model).strip()
    if chat_model != REQUIRED_CHAT_MODEL or embedding_model != REQUIRED_EMBEDDING_MODEL:
        print(_MODEL_FLAG_ERROR, file=sys.stderr)
        return 2
    try:
        prepared = _prepare()
    except _ProtocolError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not prepared.gate.ok:
        _emit_gate_failure(prepared.gate)
        return 2
    try:
        return asyncio.run(
            _evaluate(
                prepared,
                chat_model=chat_model,
                embedding_model=embedding_model,
            )
        )
    except Exception as exc:
        print(f"feedback summary eval failed: {exc}", file=sys.stderr)
        return 1


def _prepare() -> _Prepared:
    try:
        return _load_protocol()
    except _ProtocolError:
        raise
    except (OSError, ValueError, json.JSONDecodeError, UnicodeError) as exc:
        raise _ProtocolError(str(exc)) from exc


def _load_protocol() -> _Prepared:
    gold_payload = _read_json(_GOLD_PATH)
    manifest = _read_json(_MANIFEST_PATH)
    if gold_payload.get("version") != "v1":
        raise ValueError("summary gold version is not v1")
    if gold_payload.get("source_manifest") != "data/feedback/v1/manifest.json":
        raise ValueError("summary gold source_manifest is not the v1 manifest")
    questions = load_summary_gold(_GOLD_PATH)
    assert_gold_matches_manifest(questions, manifest)
    gold_sha = gold_payload.get("expected_holdout_sha256")
    manifest_sha = manifest.get("holdout_sha256")
    if not isinstance(gold_sha, str) or gold_sha != manifest_sha:
        raise ValueError("summary gold holdout sha256 does not match the manifest")
    if gold_payload.get("expected_holdout_rows") != 20 or manifest.get("holdout_rows") != 20:
        raise ValueError("holdout row count is not 20")
    rows = _read_jsonl(_CLEANED_PATH)
    _validate_cleaned(rows, manifest)
    user_prompt = _USER_PROMPT_PATH.read_text(encoding="utf-8")
    judge_prompt = _JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    _require_placeholders(user_prompt, ("question", "context"), label="summary prompt")
    _require_placeholders(
        judge_prompt,
        ("question", "context", "answer", "must_not", "expected_scenario_ids"),
        label="judge prompt",
    )
    gate = check_holdout_gate(
        holdout_bytes=_HOLDOUT_PATH.read_bytes(),
        expected_sha256=gold_sha,
        expected_rows=20,
    )
    return _Prepared(
        questions=questions,
        manifest=manifest,
        rows=rows,
        gate=gate,
        user_prompt=user_prompt,
        judge_prompt=judge_prompt,
    )


def _validate_cleaned(rows: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> None:
    if len(rows) != EXPECTED_CORPUS_ROWS:
        raise ValueError(f"cleaned has {len(rows)} rows, expected {EXPECTED_CORPUS_ROWS}")
    counts = {name: 0 for name in _CLASS_NAMES}
    indexed = {"bug": 0, "feature": 0}
    seen: set[str] = set()
    for row in rows:
        corpus_id = row.get("corpus_id")
        label = row.get("rule_class")
        flag = row.get("index_in_rag")
        index_text = row.get("index_text")
        scenario_id = row.get("scenario_id")
        if not isinstance(corpus_id, str) or not corpus_id or corpus_id in seen:
            raise ValueError(f"cleaned corpus_id is missing or duplicated: {corpus_id!r}")
        seen.add(corpus_id)
        if label not in counts:
            raise ValueError(f"{corpus_id} rule_class {label!r} is outside the four classes")
        if not isinstance(flag, bool):
            raise ValueError(f"{corpus_id} index_in_rag is not a bool")
        if not isinstance(index_text, str):
            raise ValueError(f"{corpus_id} index_text is not a string")
        if scenario_id is not None and not isinstance(scenario_id, str):
            raise ValueError(f"{corpus_id} scenario_id is not a string")
        counts[str(label)] += 1
        if flag:
            if label not in indexed:
                raise ValueError(f"{corpus_id} index_in_rag is set on {label}")
            indexed[str(label)] += 1
    observed = {**counts, "total": len(rows)}
    expected_counts = _manifest_counts(manifest)
    expected_index = _manifest_index(manifest)
    if observed != expected_counts or indexed != expected_index:
        raise ValueError(
            f"cleaned counts {observed} index {indexed} do not match manifest "
            f"{expected_counts} {expected_index}"
        )
    index_true_count = manifest.get("index_true_count")
    if not isinstance(index_true_count, int) or indexed["bug"] + indexed["feature"] != index_true_count:
        raise ValueError("cleaned index_true_count does not match the manifest")


async def _evaluate(
    prepared: _Prepared,
    *,
    chat_model: str,
    embedding_model: str,
) -> int:
    settings = get_settings()
    product_collection = settings.qdrant_collection
    ollama_base_url = settings.ollama_base_url
    client = OllamaClient(base_url=ollama_base_url, timeout_seconds=_GENERATE_TIMEOUT_SECONDS)
    try:
        probe_payload = build_eval_point_payload(prepared.rows[0])
        probe_content = str(probe_payload["content"])
        probe_vector = await client.embed(embedding_model, probe_content)
        if len(probe_vector) != EXPECTED_VECTOR_SIZE:
            print(
                f"embedding size {len(probe_vector)} != {EXPECTED_VECTOR_SIZE}",
                file=sys.stderr,
            )
            return 1
        assert_eval_collection_is_not_product(
            collection_name=EVAL_COLLECTION_NAME,
            product_collection=product_collection,
        )
        store = QdrantStore(settings.qdrant_url, EVAL_COLLECTION_NAME)
        store.ensure_collection(vector_size=EXPECTED_VECTOR_SIZE, recreate=True)
        points = await _embed_points(
            client,
            prepared.rows,
            embedding_model,
            probe_vector,
            probe_content,
        )
        if points is None:
            return 1
        for start in range(0, len(points), _UPSERT_BATCH):
            store.upsert_chunks(points[start : start + _UPSERT_BATCH])
        print(f"upserted {len(points)} into {EVAL_COLLECTION_NAME}", flush=True)
        counted = _read_collection(store, prepared)
        if counted is None:
            return 1
        eval_counts, eval_index = counted
        question_vectors: dict[str, list[float]] = {}
        for question in prepared.questions:
            vector = await client.embed(embedding_model, question.question)
            if len(vector) != EXPECTED_VECTOR_SIZE:
                print(
                    f"question embedding size {len(vector)} != {EXPECTED_VECTOR_SIZE}",
                    file=sys.stderr,
                )
                return 1
            question_vectors[question.question_id] = vector
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
            runs = await _run_arms(
                client=client,
                http=http,
                store=store,
                prepared=prepared,
                chat_model=chat_model,
                ollama_base_url=ollama_base_url,
                question_vectors=question_vectors,
            )
        document = _document(
            prepared=prepared,
            runs=runs,
            chat_model=chat_model,
            embedding_model=embedding_model,
            product_collection=product_collection,
            eval_counts=eval_counts,
            eval_index=eval_index,
        )
        _write_json(_OUTPUT_PATH, document)
        print(f"wrote {_OUTPUT_PATH} accepted={document['h1_acceptance']['accepted']}")
        return 0
    finally:
        await client.aclose()


async def _embed_points(
    client: OllamaClient,
    rows: Sequence[Mapping[str, Any]],
    embedding_model: str,
    probe_vector: list[float],
    probe_content: str,
) -> list[tuple[str, list[float], dict[str, Any]]] | None:
    points: list[tuple[str, list[float], dict[str, Any]]] = []
    probe_used = False
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        payload = build_eval_point_payload(row)
        content = str(payload["content"])
        if not probe_used and content == probe_content:
            vector = probe_vector
            probe_used = True
        else:
            vector = await client.embed(embedding_model, content)
            if len(vector) != EXPECTED_VECTOR_SIZE:
                print(
                    f"embedding size {len(vector)} != {EXPECTED_VECTOR_SIZE}",
                    file=sys.stderr,
                )
                return None
        corpus_id = str(payload["corpus_id"])
        points.append((eval_point_id(corpus_id), vector, payload))
        if index % _UPSERT_BATCH == 0 or index == total:
            print(f"embedded {index}/{total}", flush=True)
    return points


def _read_collection(
    store: QdrantStore,
    prepared: _Prepared,
) -> tuple[dict[str, int], dict[str, int]] | None:
    scrolled = store.scroll(
        limit=EXPECTED_CORPUS_ROWS,
        tenant_id=EVAL_TENANT_ID,
        bucket_ids=[EVAL_BUCKET_ID],
        index_in_rag=None,
    )
    counted = _exact_count(store)
    counts, indexed = _tally_chunks(scrolled)
    file_ids = {str(row["corpus_id"]) for row in prepared.rows}
    scrolled_ids = {str(chunk.metadata.get("corpus_id")) for chunk in scrolled}
    expected_counts = _manifest_counts(prepared.manifest)
    expected_index = _manifest_index(prepared.manifest)
    class_total = sum(counts[name] for name in _CLASS_NAMES)
    matched = (
        len(scrolled) == EXPECTED_CORPUS_ROWS
        and counted == EXPECTED_CORPUS_ROWS
        and scrolled_ids == file_ids
        and counts == expected_counts
        and indexed == expected_index
        and class_total == EXPECTED_CORPUS_ROWS
        and indexed["bug"] + indexed["feature"] == int(prepared.manifest["index_true_count"])
    )
    if not matched:
        print(
            "eval collection counts did not match the manifest: "
            f"scrolled={len(scrolled)} counted={counted} classes={counts} indexed={indexed}",
            file=sys.stderr,
        )
        return None
    print(f"eval collection rows={len(scrolled)}", flush=True)
    return counts, indexed


def _exact_count(store: QdrantStore) -> int:
    """Count every point in the eval tenant. Scroll's page cannot reveal a 511th row."""

    counted = store._client.count(
        collection_name=store.collection_name,
        count_filter=_payload_filter(
            EVAL_TENANT_ID,
            [EVAL_BUCKET_ID],
            [],
            [],
            [],
            [],
            index_in_rag=None,
        ),
        exact=True,
    )
    return int(counted.count)


def _tally_chunks(chunks: Sequence[SourceChunk]) -> tuple[dict[str, int], dict[str, int]]:
    counts = {name: 0 for name in _CLASS_NAMES}
    indexed = {"bug": 0, "feature": 0}
    for chunk in chunks:
        label = chunk.metadata.get("feedback_class")
        if label in counts:
            counts[str(label)] += 1
        if chunk.metadata.get("index_in_rag") is True and label in indexed:
            indexed[str(label)] += 1
    return {**counts, "total": len(chunks)}, indexed


async def _run_arms(
    *,
    client: OllamaClient,
    http: httpx.AsyncClient,
    store: QdrantStore,
    prepared: _Prepared,
    chat_model: str,
    ollama_base_url: str,
    question_vectors: Mapping[str, Sequence[float]],
) -> list[_Run]:
    runs: list[_Run] = []
    for arm in _ARM_ORDER:
        for question in prepared.questions:
            vector = list(question_vectors[question.question_id])
            for repeat in range(1, EVAL_REPEATS + 1):
                run = await _one_run(
                    client=client,
                    http=http,
                    store=store,
                    prepared=prepared,
                    chat_model=chat_model,
                    ollama_base_url=ollama_base_url,
                    arm=arm,
                    question=question,
                    query_vector=vector,
                    repeat=repeat,
                )
                runs.append(run)
                print(
                    f"{arm} {question.question_id} repeat={repeat} "
                    f"recall={run.markers.retrieval_recall:.3f} "
                    f"faithfulness={run.markers.faithfulness:.3f}",
                    flush=True,
                )
    return runs


async def _one_run(
    *,
    client: OllamaClient,
    http: httpx.AsyncClient,
    store: QdrantStore,
    prepared: _Prepared,
    chat_model: str,
    ollama_base_url: str,
    arm: Literal["H0", "H1"],
    question: GoldQuestion,
    query_vector: list[float],
    repeat: int,
) -> _Run:
    chunks = retrieve_arm(
        store,
        arm=arm,
        query_vector=query_vector,
        tenant_id=EVAL_TENANT_ID,
        bucket_id=EVAL_BUCKET_ID,
        top_k=EVAL_TOP_K,
    )
    sources = [retrieved_source_from_chunk(chunk) for chunk in chunks]
    context = _context(sources)
    prompt = _render(prepared.user_prompt, question=question.question, context=context)
    started = time.perf_counter()
    generated = await client.generate(
        chat_model,
        prompt,
        keep_alive=EVAL_KEEP_ALIVE,
        options={
            "temperature": EVAL_TEMPERATURE,
            "top_p": EVAL_TOP_P,
            "num_ctx": EVAL_NUM_CTX,
        },
        think=False,
    )
    latency_ms_wall = int((time.perf_counter() - started) * 1000)
    ollama_ps = await _read_ps(http, ollama_base_url, chat_model)
    answer = _response_text(generated)
    markers = score_markers(
        gold=question,
        answer=answer,
        sources=sources,
        vocabulary=SCENARIO_IDS,
    )
    judge_prompt = _render(
        prepared.judge_prompt,
        question=question.question,
        context=context,
        answer=answer,
        must_not="\n".join(question.must_not),
        expected_scenario_ids="\n".join(question.expected_scenario_ids),
    )
    judged = await client.generate(
        chat_model,
        judge_prompt,
        keep_alive=EVAL_KEEP_ALIVE,
        options={"temperature": _JUDGE_TEMPERATURE, "num_ctx": EVAL_NUM_CTX},
        think=False,
    )
    judge = parse_judge_payload(_response_text(judged))
    diverged = None if judge is None else judge_diverged(markers=markers, judge=judge)
    return _Run(
        arm=arm,
        question=question,
        repeat=repeat,
        answer=answer,
        latency_ms=_ns_to_ms(generated, "total_duration"),
        eval_duration_ms=_ns_to_ms(generated, "eval_duration"),
        load_duration_ms=_ns_to_ms(generated, "load_duration"),
        latency_ms_wall=latency_ms_wall,
        ollama_ps=ollama_ps,
        sources=sources,
        scores=[_json_score(chunk.score) for chunk in chunks],
        markers=markers,
        judge=judge,
        diverged=diverged,
    )


def _document(
    *,
    prepared: _Prepared,
    runs: Sequence[_Run],
    chat_model: str,
    embedding_model: str,
    product_collection: str,
    eval_counts: Mapping[str, int],
    eval_index: Mapping[str, int],
) -> dict[str, Any]:
    bugs_h0 = _markers(runs, arm="H0", slice_name="bug")
    bugs_h1 = _markers(runs, arm="H1", slice_name="bug")
    acceptance = asdict(accept_h1(bugs_h0=bugs_h0, bugs_h1=bugs_h1))
    acceptance["fixed_thresholds_not_used"] = True
    bug_question = prepared.questions[0]
    return {
        "stage": 3,
        "decision_source": "markers",
        "protocol": {
            "chat_model": chat_model,
            "chat_model_source": "cli_flag",
            "embedding_model": embedding_model,
            "embedding_model_source": "cli_flag",
            "product_defaults_not_used": True,
            "temperature": EVAL_TEMPERATURE,
            "top_p": EVAL_TOP_P,
            "judge_temperature": _JUDGE_TEMPERATURE,
            "top_k": EVAL_TOP_K,
            "repeats": EVAL_REPEATS,
            "num_ctx": EVAL_NUM_CTX,
            "think": False,
            "keep_alive": EVAL_KEEP_ALIVE,
            "collection": EVAL_COLLECTION_NAME,
            "product_collection": product_collection,
            "tenant_id": EVAL_TENANT_ID,
            "bucket_id": EVAL_BUCKET_ID,
            "h0_index_in_rag": None,
            "h1_index_in_rag": True,
            "prompt_path": _PROMPT_PATH,
            "judge_prompt_path": _JUDGE_PATH,
        },
        "holdout_gate": {
            "ok": prepared.gate.ok,
            "rows": prepared.gate.rows,
            "sha256": prepared.gate.sha256,
            "mismatches": [asdict(item) for item in prepared.gate.mismatches],
        },
        "volume": {
            "source": "manifest_checked_against_eval_collection",
            "postgres": None,
            "postgres_reason": _POSTGRES_REASON,
            "counts": _manifest_counts(prepared.manifest),
            "index_true_count": prepared.manifest["index_true_count"],
            "index_true_by_class": _manifest_index(prepared.manifest),
            "eval_collection_counts": dict(eval_counts),
            "eval_index_true_by_class": dict(eval_index),
            "match": True,
        },
        "runs": [_run_payload(run) for run in runs],
        "summary": {
            "critical_bugs": {
                "H0": _arm_summary(runs, question_id="critical_bugs", arm="H0"),
                "H1": _arm_summary(runs, question_id="critical_bugs", arm="H1"),
            },
            "requested_features": {
                "H0": _arm_summary(runs, question_id="requested_features", arm="H0"),
                "H1": _arm_summary(runs, question_id="requested_features", arm="H1"),
            },
        },
        "h1_acceptance": acceptance,
        "h2": h2_note(
            bugs_h1_sources=[
                run.sources for run in runs if run.arm == "H1" and run.question.slice == "bug"
            ],
            expected_scenario_ids=bug_question.expected_scenario_ids,
            top_k=EVAL_TOP_K,
        ),
    }


def _run_payload(run: _Run) -> dict[str, Any]:
    return {
        "arm": run.arm,
        "question_id": run.question.question_id,
        "slice": run.question.slice,
        "repeat": run.repeat,
        "answer": run.answer,
        "latency_ms": run.latency_ms,
        "eval_duration_ms": run.eval_duration_ms,
        "load_duration_ms": run.load_duration_ms,
        "latency_ms_wall": run.latency_ms_wall,
        "ollama_ps": run.ollama_ps,
        "sources": [
            {
                "corpus_id": source.corpus_id,
                "scenario_id": source.scenario_id,
                "index_in_rag": source.index_in_rag,
                "score": score,
                "content": source.content,
            }
            for source, score in zip(run.sources, run.scores, strict=True)
        ],
        "markers": asdict(run.markers),
        "judge": None if run.judge is None else asdict(run.judge),
        "diverged": run.diverged,
    }


def _arm_summary(runs: Sequence[_Run], *, question_id: str, arm: str) -> dict[str, Any]:
    selected = [run for run in runs if run.question.question_id == question_id and run.arm == arm]
    scores = [run.markers for run in selected]
    return {
        "retrieval_recall_mean": mean_metric(scores, "retrieval_recall"),
        "faithfulness_mean": mean_metric(scores, "faithfulness"),
        "answer_coverage_mean": mean_metric(scores, "answer_coverage"),
        "must_not_hit_runs": sum(1 for score in scores if score.must_not_hits),
        "judge_faithfulness_mean": _optional_mean(
            [None if run.judge is None else run.judge.faithfulness for run in selected]
        ),
        "judge_answer_coverage_mean": _optional_mean(
            [None if run.judge is None else run.judge.answer_coverage for run in selected]
        ),
    }


def _markers(runs: Sequence[_Run], *, arm: str, slice_name: str) -> list[MarkerScore]:
    return [run.markers for run in runs if run.arm == arm and run.question.slice == slice_name]


def _context(sources: Sequence[RetrievedSource]) -> str:
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        scenario_id = source.scenario_id if source.scenario_id else "none"
        blocks.append(f"[Источник {index} | scenario_id={scenario_id}]\n{source.content}")
    return "\n\n".join(blocks)


def _render(template: str, **fields: str) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in fields:
            raise KeyError(key)
        return fields[key]

    return _PLACEHOLDER_RE.sub(replace, template)


def _require_placeholders(template: str, names: Sequence[str], *, label: str) -> None:
    missing = [name for name in names if "{" + name + "}" not in template]
    if missing:
        raise ValueError(f"{label} is missing {', '.join(missing)}")


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


def _json_score(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value)


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


def _optional_mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _manifest_counts(manifest: Mapping[str, Any]) -> dict[str, int]:
    return _int_map(manifest.get("counts"), (*_CLASS_NAMES, "total"), field="manifest.counts")


def _manifest_index(manifest: Mapping[str, Any]) -> dict[str, int]:
    return _int_map(manifest.get("index_true_by_class"), ("bug", "feature"), field="manifest.index_true_by_class")


def _int_map(value: object, keys: Sequence[str], *, field: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} is missing")
    parsed: dict[str, int] = {}
    for key in keys:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{field}.{key} is not an int")
        parsed[key] = item
    return parsed


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not an object")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}:{line_no} is not an object")
        rows.append(payload)
    return rows


def _emit_gate_failure(gate: HoldoutGateResult) -> None:
    print(
        f"holdout gate failed: ok={gate.ok} rows={gate.rows} sha256={gate.sha256}",
        file=sys.stderr,
    )
    for item in gate.mismatches:
        print(
            f"line {item.line_no}: manual_class={item.manual_class} "
            f"rule_class={item.rule_class} text={item.text_preview}",
            file=sys.stderr,
        )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(partial, path)


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic cleaning for the v1 feedback corpus.

Rules separate noise and churn from bugs and features, mask phone and card
text, and set index_in_rag. The indexing worker reads that flag; it does
not compute it. Holdout text is not part of the lexicon.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FeedbackItem
from app.services.feedback_index_policy import FEEDBACK_CLASSES, PRODUCT_INDEX_CLASSES

SCENARIO_IDS: frozenset[str] = frozenset(
    {
        "notifications",
        "csv_import",
        "permissions",
        "reports",
        "search",
        "webhooks",
        "integrations",
        "tasks",
        "projects",
        "sprints",
    }
)
INDEX_TEXT_MAX_CHARS: int = 1200
CORPUS_ID_PREFIX: str = "fb-v1-"
EXACT_BUG_COPIES: int = 8
EXACT_FEATURE_COPIES: int = 2
TARGET_SHARES: dict[str, float] = {
    "noise": 0.70,
    "churn_signal": 0.15,
    "bug": 0.12,
    "feature": 0.03,
}
TOLERANCE_PP: float = 2.0

_CLASS_ORDER = ("noise", "churn_signal", "bug", "feature")
_EXPECTED_ROWS = {
    "noise": 350,
    "churn_signal": 75,
    "bug": 60,
    "feature": 15,
}
_CANONICAL_NOISE = Path("/home/santera/ML|LLM|RAG/sintetic_data/noise.jsonl")
_CANONICAL_CHURN = Path("/home/santera/ML|LLM|RAG/sintetic_data/churn.jsonl")
_PHONE_RE = re.compile(r"\+7\s*\d{3}\s*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
_CARD_RE = re.compile(r"\b\d{4}(?:\s+\d{4}){3}\b")
_INNER_SPACE_RE = re.compile(r"\s+")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_lexicon_cache: tuple[frozenset[str], frozenset[str]] | None = None


class _AssemblySources:
    """Source-file hashes for one assemble_raw_rows call.

    Keyed by the identity of that call's FeedbackSourceRow objects, so a
    later assembly cannot replace the hashes of an earlier one.
    """

    def __init__(self, sources: list[dict[str, object]]) -> None:
        self.sources = sources
        self.rows: list[FeedbackSourceRow] = []

    def bind(self, row: FeedbackSourceRow) -> None:
        self.rows.append(row)
        _sources_by_row_id[id(row)] = self


_sources_by_row_id: dict[int, _AssemblySources] = {}


def _bind_assembly(rows: Sequence[FeedbackSourceRow], sources: list[dict[str, object]]) -> None:
    record = _AssemblySources(sources)
    for row in rows:
        record.bind(row)


def _rebind_source(previous: FeedbackSourceRow, updated: FeedbackSourceRow) -> None:
    record = _sources_by_row_id.get(id(previous))
    if record is not None:
        record.bind(updated)


def _assembly_for(rows: Sequence[FeedbackSourceRow]) -> _AssemblySources:
    found: _AssemblySources | None = None
    seen = False
    for row in rows:
        seen = True
        record = _sources_by_row_id.get(id(row))
        if record is None:
            raise ValueError(
                f"row {row.corpus_id} was not assembled in this process; "
                "refusing to reuse another assembly's source hashes"
            )
        if found is None:
            found = record
        elif found is not record:
            raise ValueError("rows come from different assemblies; refusing to mix source hashes")
    if not seen or found is None:
        raise ValueError("these rows were not assembled in this process")
    return found


@dataclass(frozen=True)
class FeedbackSourceRow:
    corpus_id: str
    generator_class: str
    scenario_id: str | None
    text: str
    source_file: str
    source_line: int
    is_exact_duplicate: bool
    duplicate_of: str | None


@dataclass(frozen=True)
class FeedbackCleanedRow:
    source: FeedbackSourceRow
    rule_class: str
    index_in_rag: bool
    rule_reason: str
    index_text: str
    index_text_truncated: bool


def normalize_lexicon_key(text: str) -> str:
    folded = unicodedata.normalize("NFC", text).strip().casefold()
    return _INNER_SPACE_RE.sub(" ", folded)


def mask_pii(text: str) -> str:
    masked = _PHONE_RE.sub("[PHONE]", text)
    return _CARD_RE.sub("[CARD]", masked)


def slice_index_text(text: str, *, max_chars: int = INDEX_TEXT_MAX_CHARS) -> tuple[str, bool]:
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def lexicon_rule_class(text: str, *, fallback_class: str) -> tuple[str, str]:
    """Return ``(rule_class, rule_reason)`` from the closed lexicons.

    A phrase in both lexicons is churn. Noise alone is noise, churn alone is
    churn, and every other phrase keeps ``fallback_class``. This does not
    suppress exact duplicates and does not require a fallback noise phrase to
    sit in the lexicon. ``fallback_class`` outside the four classes raises
    ``ValueError``.
    """

    if fallback_class not in FEEDBACK_CLASSES:
        raise ValueError(
            f"fallback class {fallback_class!r} is outside the four feedback classes"
        )
    noise_lexicon, churn_lexicon = _closed_lexicons()
    key = normalize_lexicon_key(text)
    in_noise = key in noise_lexicon
    in_churn = key in churn_lexicon
    if in_noise and in_churn:
        return "churn_signal", "lexicon_churn"
    if in_noise:
        return "noise", "lexicon_noise"
    if in_churn:
        return "churn_signal", "lexicon_churn"
    return fallback_class, "keep_generator"


def rule_class_for_labeled_text(*, text: str, manual_class: str) -> str:
    """Class used by the holdout gate. Returns only the lexicon rule class."""

    rule_class, _reason = lexicon_rule_class(text, fallback_class=manual_class)
    return rule_class


def apply_feedback_rules(rows: Sequence[FeedbackSourceRow]) -> list[FeedbackCleanedRow]:
    noise_lexicon, churn_lexicon = _closed_lexicons()
    staged: list[tuple[FeedbackSourceRow, str, str, str, bool]] = []
    for row in rows:
        if row.generator_class not in FEEDBACK_CLASSES:
            raise ValueError(
                f"{row.corpus_id} class {row.generator_class!r} is outside the four feedback classes"
            )
        key = normalize_lexicon_key(row.text)
        if row.generator_class == "noise" and key not in noise_lexicon:
            raise ValueError(f"{row.corpus_id} noise phrase is outside the closed lexicon")
        if row.generator_class == "churn_signal" and key not in churn_lexicon:
            raise ValueError(f"{row.corpus_id} churn phrase is outside the closed lexicon")
        rule_class, rule_reason = lexicon_rule_class(row.text, fallback_class=row.generator_class)
        index_text, truncated = slice_index_text(mask_pii(row.text))
        staged.append((row, rule_class, rule_reason, index_text, truncated))

    seen: dict[str, str] = {}
    cleaned: list[FeedbackCleanedRow] = []
    for source, rule_class, rule_reason, index_text, truncated in staged:
        class_name = rule_class
        duplicate = False
        if class_name in PRODUCT_INDEX_CLASSES:
            duplicate_key = unicodedata.normalize("NFC", source.text)
            first_id = seen.get(duplicate_key)
            if first_id is None:
                seen[duplicate_key] = source.corpus_id
            else:
                duplicate = True
                rule_reason = "exact_duplicate"
                if source.duplicate_of != first_id:
                    previous = source
                    source = replace(source, duplicate_of=first_id)
                    _rebind_source(previous, source)
        index_in_rag = (
            class_name in PRODUCT_INDEX_CLASSES
            and not duplicate
            and bool(index_text.strip())
        )
        cleaned.append(
            FeedbackCleanedRow(
                source=source,
                rule_class=class_name,
                index_in_rag=index_in_rag,
                rule_reason=rule_reason,
                index_text=index_text,
                index_text_truncated=truncated,
            )
        )
    return cleaned


def assemble_raw_rows(
    *,
    noise_path: Path,
    churn_path: Path,
    bugs_path: Path,
    features_path: Path,
) -> list[FeedbackSourceRow]:
    noise_lexicon, churn_lexicon = _closed_lexicons()
    specs = (
        (noise_path, "noise", noise_lexicon),
        (churn_path, "churn_signal", churn_lexicon),
        (bugs_path, "bug", None),
        (features_path, "feature", None),
    )
    rows: list[FeedbackSourceRow] = []
    by_class: dict[str, list[FeedbackSourceRow]] = {name: [] for name in _EXPECTED_ROWS}
    sources: list[dict[str, object]] = []
    next_index = 1
    for path, expected_class, lexicon in specs:
        digest, records = _read_jsonl(path)
        expected_count = _EXPECTED_ROWS[expected_class]
        if len(records) != expected_count:
            raise ValueError(f"{path.name} has {len(records)} rows, expected {expected_count}")
        sources.append(
            {
                "path": path.as_posix(),
                "rows": len(records),
                "sha256": digest,
            }
        )
        for line_no, payload in records:
            generator_class = _generator_class(
                payload,
                path=path,
                line_no=line_no,
                expected=expected_class,
            )
            text = _text(payload, path=path, line_no=line_no)
            if lexicon is not None and normalize_lexicon_key(text) not in lexicon:
                raise ValueError(
                    f"{path.name}:{line_no} {expected_class} phrase is outside the closed lexicon"
                )
            scenario_id = _scenario_id(
                payload.get("scenario_id"),
                path=path,
                line_no=line_no,
                required=expected_class in PRODUCT_INDEX_CLASSES,
            )
            row = FeedbackSourceRow(
                corpus_id=_corpus_id(next_index),
                generator_class=generator_class,
                scenario_id=scenario_id,
                text=text,
                source_file=path.name,
                source_line=line_no,
                is_exact_duplicate=False,
                duplicate_of=None,
            )
            next_index += 1
            rows.append(row)
            by_class[expected_class].append(row)

    for source in by_class["bug"][:EXACT_BUG_COPIES]:
        rows.append(_copied(source, corpus_id=_corpus_id(next_index)))
        next_index += 1
    for source in by_class["feature"][:EXACT_FEATURE_COPIES]:
        rows.append(_copied(source, corpus_id=_corpus_id(next_index)))
        next_index += 1
    _assert_assembly(rows)
    _bind_assembly(rows, sources)
    return rows


def build_manifest(rows: Sequence[FeedbackCleanedRow], *, holdout_path: Path) -> dict[str, object]:
    assembly = _assembly_for([row.source for row in rows])
    before, before_total = _tally(rows, before_duplicates=True)
    after, after_total = _tally(rows, before_duplicates=False)
    shares = {
        name: round(after[name] / after_total, 6) if after_total else 0.0
        for name in _CLASS_ORDER
    }
    within = after_total > 0 and all(
        abs((after[name] / after_total) - target) * 100 <= TOLERANCE_PP
        for name, target in TARGET_SHARES.items()
    )
    index_true = _index_true_by_class(rows)
    holdout_bytes = holdout_path.read_bytes()
    holdout_rows = sum(1 for line in holdout_bytes.decode("utf-8").splitlines() if line.strip())
    return {
        "version": "v1",
        "sources": [dict(item) for item in assembly.sources],
        "assembly_order": [Path(str(item["path"])).name for item in assembly.sources],
        "exact_copies": {"bug": EXACT_BUG_COPIES, "feature": EXACT_FEATURE_COPIES},
        "counts_before_duplicates": {**before, "total": before_total},
        "counts": {**after, "total": after_total},
        "shares": shares,
        "target_shares": dict(TARGET_SHARES),
        "tolerance_pp": TOLERANCE_PP,
        "shares_within_tolerance": within,
        "scenarios_unique": _scenarios(rows, indexed=False),
        "scenarios_indexed": _scenarios(rows, indexed=True),
        "missing_scenario_id_bug_feature": _missing_scenario_count(rows),
        "length": _length_bounds(rows),
        "index_text_max_chars": INDEX_TEXT_MAX_CHARS,
        "pii_raw_counts": _pii_raw_counts(rows),
        "index_true_count": index_true["bug"] + index_true["feature"],
        "index_true_by_class": index_true,
        "holdout_path": _display_path(holdout_path),
        "holdout_rows": holdout_rows,
        "holdout_sha256": hashlib.sha256(holdout_bytes).hexdigest(),
    }


def build_rule_report(rows: Sequence[FeedbackCleanedRow]) -> dict[str, object]:
    mismatches: list[dict[str, object]] = []
    suppressed: list[dict[str, object]] = []
    index_true = 0
    for row in rows:
        if row.index_in_rag:
            index_true += 1
        if row.rule_class != row.source.generator_class:
            mismatches.append(
                {
                    "corpus_id": row.source.corpus_id,
                    "generator_class": row.source.generator_class,
                    "rule_class": row.rule_class,
                    "rule_reason": row.rule_reason,
                    "text_preview": row.source.text[:80],
                }
            )
        if row.rule_reason == "exact_duplicate":
            suppressed.append(
                {
                    "corpus_id": row.source.corpus_id,
                    "duplicate_of": row.source.duplicate_of,
                    "rule_reason": row.rule_reason,
                    "generator_class": row.source.generator_class,
                    "rule_class": row.rule_class,
                }
            )
    return {
        "rows": len(rows),
        "class_mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "index_suppressed": suppressed,
        "index_true_count": index_true,
    }


def write_corpus_files(
    *,
    out_dir: Path,
    raw_rows: Sequence[FeedbackSourceRow],
    cleaned_rows: Sequence[FeedbackCleanedRow],
    holdout_path: Path,
) -> None:
    raw_assembly = _assembly_for(raw_rows)
    cleaned_assembly = _assembly_for([row.source for row in cleaned_rows])
    if raw_assembly is not cleaned_assembly:
        raise ValueError("raw_rows and cleaned_rows come from different assemblies")
    manifest = build_manifest(cleaned_rows, holdout_path=holdout_path)
    report = build_rule_report(cleaned_rows)
    outputs = (
        (out_dir / "raw.jsonl", _jsonl(_raw_payload(row) for row in raw_rows)),
        (out_dir / "cleaned.jsonl", _jsonl(_cleaned_payload(row) for row in cleaned_rows)),
        (out_dir / "manifest.json", _json_document(manifest)),
        (out_dir / "rule_report.json", _json_document(report)),
    )
    for path, _content in outputs:
        _refuse_holdout_write(path, holdout_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    for path, content in outputs:
        _refuse_holdout_write(path, holdout_path)
        path.write_text(content, encoding="utf-8")


def feedback_chunk_content(*, body: str, index_text: str | None) -> str:
    raw = body if index_text is None else index_text
    sliced, _truncated = slice_index_text(mask_pii(raw.strip()))
    return sliced


async def seed_feedback_items(
    session: AsyncSession,
    *,
    tenant_id: str,
    bucket_id: str,
    cleaned_rows: Sequence[FeedbackCleanedRow],
) -> int:
    await session.execute(
        delete(FeedbackItem)
        .where(
            FeedbackItem.tenant_id == tenant_id,
            FeedbackItem.bucket_id == bucket_id,
            FeedbackItem.corpus_id.like(f"{CORPUS_ID_PREFIX}%"),
        )
        .execution_options(synchronize_session=False)
    )
    items = [
        FeedbackItem(
            id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"feedback-v1:{tenant_id}:{bucket_id}:{row.source.corpus_id}",
                )
            ),
            tenant_id=tenant_id,
            bucket_id=bucket_id,
            document_id=None,
            feedback_class=row.rule_class,
            body=row.source.text,
            index_in_rag=row.index_in_rag,
            generator_class=row.source.generator_class,
            rule_class=row.rule_class,
            scenario_id=row.source.scenario_id,
            index_text=row.index_text,
            corpus_id=row.source.corpus_id,
            rule_reason=row.rule_reason,
            duplicate_of=row.source.duplicate_of,
        )
        for row in cleaned_rows
    ]
    session.add_all(items)
    return len(items)


def _closed_lexicons() -> tuple[frozenset[str], frozenset[str]]:
    global _lexicon_cache
    if _lexicon_cache is None:
        _lexicon_cache = (_phrases(_CANONICAL_NOISE), _phrases(_CANONICAL_CHURN))
    return _lexicon_cache


def _phrases(path: Path) -> frozenset[str]:
    _digest, records = _read_jsonl(path)
    return frozenset(normalize_lexicon_key(_text(payload, path=path, line_no=line_no)) for line_no, payload in records)


def _read_jsonl(path: Path) -> tuple[str, list[tuple[int, dict[str, object]]]]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    records: list[tuple[int, dict[str, object]]] = []
    for line_no, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{line_no} is not valid json") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}:{line_no} is not an object")
        records.append((line_no, payload))
    return digest, records


def _generator_class(
    payload: dict[str, object],
    *,
    path: Path,
    line_no: int,
    expected: str,
) -> str:
    value = payload.get("generator_class")
    if not isinstance(value, str) or value not in FEEDBACK_CLASSES:
        raise ValueError(f"{path.name}:{line_no} class {value!r} is outside the four feedback classes")
    if value != expected:
        raise ValueError(f"{path.name}:{line_no} generator_class {value!r} does not match {expected}")
    return value


def _text(payload: dict[str, object], *, path: Path, line_no: int) -> str:
    value = payload.get("text")
    if not isinstance(value, str):
        raise ValueError(f"{path.name}:{line_no} text is not a string")
    return value


def _scenario_id(
    value: object,
    *,
    path: Path,
    line_no: int,
    required: bool,
) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{path.name}:{line_no} missing scenario_id from SCENARIO_IDS")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{path.name}:{line_no} scenario_id is not a string")
    if required and value not in SCENARIO_IDS:
        raise ValueError(f"{path.name}:{line_no} scenario_id {value!r} is outside SCENARIO_IDS")
    return value


def _corpus_id(index: int) -> str:
    return f"{CORPUS_ID_PREFIX}{index:04d}"


def _copied(source: FeedbackSourceRow, *, corpus_id: str) -> FeedbackSourceRow:
    return FeedbackSourceRow(
        corpus_id=corpus_id,
        generator_class=source.generator_class,
        scenario_id=source.scenario_id,
        text=source.text,
        source_file=source.source_file,
        source_line=source.source_line,
        is_exact_duplicate=True,
        duplicate_of=source.corpus_id,
    )


def _assert_assembly(rows: list[FeedbackSourceRow]) -> None:
    noise_n = _EXPECTED_ROWS["noise"]
    churn_n = _EXPECTED_ROWS["churn_signal"]
    bug_n = _EXPECTED_ROWS["bug"]
    feature_n = _EXPECTED_ROWS["feature"]
    bug_start = noise_n + churn_n
    feature_start = bug_start + bug_n
    copy_start = feature_start + feature_n
    expected = copy_start + EXACT_BUG_COPIES + EXACT_FEATURE_COPIES
    if len(rows) != expected:
        raise ValueError(f"assembled {len(rows)} rows, expected {expected}")
    ids = [_corpus_id(index) for index in range(1, expected + 1)]
    if [row.corpus_id for row in rows] != ids:
        raise ValueError("corpus_id sequence drifted")
    if any(row.is_exact_duplicate or row.duplicate_of is not None for row in rows[:copy_start]):
        raise ValueError("only appended copies may be exact duplicates")
    pairs = [(copy_start + offset, bug_start + offset) for offset in range(EXACT_BUG_COPIES)]
    pairs.extend(
        (copy_start + EXACT_BUG_COPIES + offset, feature_start + offset)
        for offset in range(EXACT_FEATURE_COPIES)
    )
    for copy_index, origin_index in pairs:
        copy = rows[copy_index]
        origin = rows[origin_index]
        if (
            not copy.is_exact_duplicate
            or copy.duplicate_of != origin.corpus_id
            or copy.text != origin.text
            or copy.generator_class != origin.generator_class
            or copy.scenario_id != origin.scenario_id
            or copy.source_file != origin.source_file
            or copy.source_line != origin.source_line
        ):
            raise ValueError(f"{copy.corpus_id} is not an exact copy of {origin.corpus_id}")


def _tally(
    rows: Sequence[FeedbackCleanedRow],
    *,
    before_duplicates: bool,
) -> tuple[dict[str, int], int]:
    counts = {name: 0 for name in _CLASS_ORDER}
    total = 0
    for row in rows:
        if before_duplicates and row.source.is_exact_duplicate:
            continue
        label = row.source.generator_class if before_duplicates else row.rule_class
        if label in counts:
            counts[label] += 1
        total += 1
    return counts, total


def _index_true_by_class(rows: Sequence[FeedbackCleanedRow]) -> dict[str, int]:
    counts = {"bug": 0, "feature": 0}
    for row in rows:
        if row.index_in_rag and row.rule_class in counts:
            counts[row.rule_class] += 1
    return counts


def _scenarios(rows: Sequence[FeedbackCleanedRow], *, indexed: bool) -> dict[str, list[str]]:
    found: dict[str, set[str]] = {"bug": set(), "feature": set()}
    for row in rows:
        if row.rule_class not in found:
            continue
        if indexed and not row.index_in_rag:
            continue
        if row.source.scenario_id is not None:
            found[row.rule_class].add(row.source.scenario_id)
    return {name: sorted(values) for name, values in found.items()}


def _missing_scenario_count(rows: Sequence[FeedbackCleanedRow]) -> int:
    missing = 0
    for row in rows:
        if row.rule_class not in PRODUCT_INDEX_CLASSES:
            continue
        if row.source.scenario_id not in SCENARIO_IDS:
            missing += 1
    return missing


def _length_bounds(rows: Sequence[FeedbackCleanedRow]) -> dict[str, dict[str, int]]:
    lengths: dict[str, list[int]] = {name: [] for name in _CLASS_ORDER}
    for row in rows:
        if row.rule_class in lengths:
            lengths[row.rule_class].append(len(row.source.text))
    return {
        name: {"min": min(values), "max": max(values)}
        for name, values in lengths.items()
        if values
    }


def _pii_raw_counts(rows: Sequence[FeedbackCleanedRow]) -> dict[str, int]:
    phone = 0
    card = 0
    for row in rows:
        phone += len(_PHONE_RE.findall(row.source.text))
        card += len(_CARD_RE.findall(row.source.text))
    return {"phone": phone, "card": card}


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _raw_payload(row: FeedbackSourceRow) -> dict[str, object]:
    return {
        "corpus_id": row.corpus_id,
        "generator_class": row.generator_class,
        "scenario_id": row.scenario_id,
        "text": row.text,
        "source_file": row.source_file,
        "source_line": row.source_line,
        "is_exact_duplicate": row.is_exact_duplicate,
        "duplicate_of": row.duplicate_of,
    }


def _cleaned_payload(row: FeedbackCleanedRow) -> dict[str, object]:
    payload = _raw_payload(row.source)
    payload["rule_class"] = row.rule_class
    payload["index_in_rag"] = row.index_in_rag
    payload["rule_reason"] = row.rule_reason
    payload["index_text"] = row.index_text
    payload["index_text_truncated"] = row.index_text_truncated
    return payload


def _jsonl(payloads: Sequence[dict[str, object]]) -> str:
    return "".join(json.dumps(payload, ensure_ascii=False) + "\n" for payload in payloads)


def _json_document(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _refuse_holdout_write(path: Path, holdout_path: Path) -> None:
    if path.name == "holdout.jsonl" or path.resolve() == holdout_path.resolve():
        raise ValueError("refusing to open holdout.jsonl for writing")

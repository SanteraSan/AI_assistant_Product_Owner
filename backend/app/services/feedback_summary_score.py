"""Marker scores, holdout gate, and H1 acceptance for the feedback summary.

No network and no Qdrant. Vocabulary tokens come from the caller. The holdout
gate reads bytes it is given and does not call ``apply_feedback_rules``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.services.feedback_rules import rule_class_for_labeled_text

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_DIVERGENCE_LIMIT = 0.05
_QUESTION_SPECS = (
    ("critical_bugs", "bug"),
    ("requested_features", "feature"),
)
_METRIC_NAMES = ("retrieval_recall", "faithfulness", "answer_coverage")
_H2_REPEAT_REASON = "every H1 search repeats a scenario while a gold id is missing"
_H2_K_CAP_REASON = "recall capped by k, not by repeated scenarios"

REGRESSION_EPSILON: float = 1e-9


@dataclass(frozen=True)
class GoldQuestion:
    question_id: Literal["critical_bugs", "requested_features"]
    slice: Literal["bug", "feature"]
    question: str
    expected_scenario_ids: tuple[str, ...]
    must_not: tuple[str, ...]


@dataclass(frozen=True)
class RetrievedSource:
    corpus_id: str
    scenario_id: str | None
    index_in_rag: bool
    content: str


@dataclass(frozen=True)
class MarkerScore:
    retrieval_recall: float
    faithfulness: float
    answer_coverage: float
    support_ratio: float
    retrieved_scenario_ids: tuple[str, ...]
    answer_scenario_ids: tuple[str, ...]
    supported_scenario_ids: tuple[str, ...]
    unsupported_scenario_ids: tuple[str, ...]
    covered_scenario_ids: tuple[str, ...]
    must_not_hits: tuple[str, ...]


@dataclass(frozen=True)
class JudgeScore:
    faithfulness: float
    answer_coverage: float
    must_not_present: bool
    scenario_ids: tuple[str, ...]


@dataclass(frozen=True)
class HoldoutMismatch:
    line_no: int
    manual_class: str
    rule_class: str
    text_preview: str


@dataclass(frozen=True)
class HoldoutGateResult:
    ok: bool
    rows: int
    sha256: str
    mismatches: tuple[HoldoutMismatch, ...]


@dataclass(frozen=True)
class H1Acceptance:
    bugs_must_not_cleared: bool
    bugs_must_not_hit_runs_h0: int
    bugs_must_not_hit_runs_h1: int
    bugs_must_not_already_clear_in_h0: bool
    faithfulness_not_regressed: bool
    retrieval_recall_not_regressed: bool
    accepted: bool


def load_summary_gold(path: Path) -> tuple[GoldQuestion, GoldQuestion]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not an object")
    must_not = _string_tuple(payload.get("must_not"), field="must_not")
    questions = payload.get("questions")
    if not isinstance(questions, list) or len(questions) != 2:
        raise ValueError("summary gold must contain two questions")
    parsed = [
        _gold_question(
            item,
            question_id=question_id,
            slice_name=slice_name,
            must_not=must_not,
        )
        for (question_id, slice_name), item in zip(_QUESTION_SPECS, questions, strict=True)
    ]
    return parsed[0], parsed[1]


def assert_gold_matches_manifest(
    questions: Sequence[GoldQuestion],
    manifest: Mapping[str, Any],
) -> None:
    """The bug question's ids equal ``scenarios_indexed.bug``, and the same for features.

    An empty list or an extra id raises ``ValueError``. Exactly ten ids is not required.
    """

    indexed = manifest.get("scenarios_indexed")
    if not isinstance(indexed, Mapping):
        raise ValueError("manifest scenarios_indexed is missing")
    for question in questions:
        gold_ids = _scenario_set(
            question.expected_scenario_ids,
            field=f"{question.question_id}.expected_scenario_ids",
        )
        if not gold_ids:
            raise ValueError(f"{question.question_id} expected_scenario_ids is empty")
        manifest_ids = _scenario_set(
            indexed.get(question.slice),
            field=f"scenarios_indexed.{question.slice}",
        )
        if gold_ids != manifest_ids:
            raise ValueError(
                f"{question.question_id} expected_scenario_ids do not match "
                f"scenarios_indexed.{question.slice}"
            )


def scenario_ids_in_text(text: str, *, vocabulary: frozenset[str]) -> tuple[str, ...]:
    """Vocabulary tokens on a ``[^A-Za-z0-9_]`` boundary, first occurrence, no repeats."""

    found: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0)
        if token in vocabulary and token not in seen:
            seen.add(token)
            found.append(token)
    return tuple(found)


def must_not_hits(text: str, phrases: Sequence[str]) -> tuple[str, ...]:
    """NFC plus casefold substring match. Hits keep the original phrase text."""

    folded = unicodedata.normalize("NFC", text).casefold()
    hits: list[str] = []
    for phrase in phrases:
        needle = unicodedata.normalize("NFC", phrase).casefold()
        if needle and needle in folded:
            hits.append(phrase)
    return tuple(hits)


def score_retrieval_recall(
    *,
    expected: Sequence[str],
    sources: Sequence[RetrievedSource],
) -> float:
    """Unique retrieved scenario ids that are expected, divided by unique expected ids.

    An empty scenario id does not count. A repeated scenario counts once.
    An empty expected list raises ``ValueError``.
    """

    expected_ids = _unique_expected(expected)
    retrieved = set(_unique_scenario_ids(sources))
    found = sum(1 for scenario_id in expected_ids if scenario_id in retrieved)
    return found / len(expected_ids)


def score_faithfulness(
    *,
    answer: str,
    sources: Sequence[RetrievedSource],
    must_not: Sequence[str],
    vocabulary: frozenset[str],
) -> tuple[float, float, tuple[str, ...]]:
    """Return ``(faithfulness, support_ratio, must_not_hits)``.

    ``support_ratio`` is 1 when the answer names no scenario id, otherwise the
    share of answer ids that also appear in the sources. Any must-not hit forces
    faithfulness to 0. Silence without a must-not hit is faithful and covers nothing.
    """

    hits = must_not_hits(answer, must_not)
    answer_ids = scenario_ids_in_text(answer, vocabulary=vocabulary)
    if not answer_ids:
        support_ratio = 1.0
    else:
        source_ids = set(_unique_scenario_ids(sources))
        support_ratio = sum(1 for scenario_id in answer_ids if scenario_id in source_ids) / len(answer_ids)
    faithfulness = 0.0 if hits else support_ratio
    return faithfulness, support_ratio, hits


def score_answer_coverage(
    *,
    answer: str,
    expected: Sequence[str],
    vocabulary: frozenset[str],
) -> float:
    """Share of expected ids named in the answer. An id outside expected does not count."""

    expected_ids = _unique_expected(expected)
    answer_ids = set(scenario_ids_in_text(answer, vocabulary=vocabulary))
    covered = sum(1 for scenario_id in expected_ids if scenario_id in answer_ids)
    return covered / len(expected_ids)


def score_markers(
    *,
    gold: GoldQuestion,
    answer: str,
    sources: Sequence[RetrievedSource],
    vocabulary: frozenset[str],
) -> MarkerScore:
    retrieved = _unique_scenario_ids(sources)
    answer_ids = scenario_ids_in_text(answer, vocabulary=vocabulary)
    faithfulness, support_ratio, hits = score_faithfulness(
        answer=answer,
        sources=sources,
        must_not=gold.must_not,
        vocabulary=vocabulary,
    )
    expected_ids = _unique_expected(gold.expected_scenario_ids)
    source_ids = set(retrieved)
    answer_set = set(answer_ids)
    return MarkerScore(
        retrieval_recall=score_retrieval_recall(
            expected=gold.expected_scenario_ids,
            sources=sources,
        ),
        faithfulness=faithfulness,
        answer_coverage=score_answer_coverage(
            answer=answer,
            expected=gold.expected_scenario_ids,
            vocabulary=vocabulary,
        ),
        support_ratio=support_ratio,
        retrieved_scenario_ids=retrieved,
        answer_scenario_ids=answer_ids,
        supported_scenario_ids=tuple(scenario_id for scenario_id in answer_ids if scenario_id in source_ids),
        unsupported_scenario_ids=tuple(
            scenario_id for scenario_id in answer_ids if scenario_id not in source_ids
        ),
        covered_scenario_ids=tuple(scenario_id for scenario_id in expected_ids if scenario_id in answer_set),
        must_not_hits=hits,
    )


def parse_judge_payload(text: str) -> JudgeScore | None:
    """First JSON object in ``text``. Missing fields or a number outside [0, 1] return None."""

    decoder = json.JSONDecoder()
    start = 0
    while start < len(text):
        brace = text.find("{", start)
        if brace < 0:
            return None
        try:
            payload, _end = decoder.raw_decode(text[brace:])
        except json.JSONDecodeError:
            start = brace + 1
            continue
        if isinstance(payload, dict):
            return _judge_score(payload)
        start = brace + 1
    return None


def judge_diverged(*, markers: MarkerScore, judge: JudgeScore) -> bool:
    """True when faithfulness or coverage differs by more than 0.05, or must-not disagrees.

    A gap of 0.05 is not enough. 1e-9 absorbs binary float noise so that a
    decimal gap of 0.05 stays under the limit. H1 acceptance does not read it.
    """

    if _exceeds_divergence(markers.faithfulness, judge.faithfulness):
        return True
    if _exceeds_divergence(markers.answer_coverage, judge.answer_coverage):
        return True
    return bool(markers.must_not_hits) != judge.must_not_present


def _exceeds_divergence(left: float, right: float) -> bool:
    return abs(left - right) - _DIVERGENCE_LIMIT > 1e-9


def check_holdout_gate(
    *,
    holdout_bytes: bytes,
    expected_sha256: str,
    expected_rows: int = 20,
) -> HoldoutGateResult:
    """Hash the raw bytes and compare each manual label with the lexicon class.

    ``manual_class`` is ``generator_class``. ``ok`` requires the hash, the row
    count, and an empty mismatch list. The function does not open a path and
    does not rewrite lines.
    """

    try:
        text = holdout_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("holdout is not utf-8") from exc
    mismatches: list[HoldoutMismatch] = []
    rows = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        rows += 1
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"holdout:{line_no} is not valid json") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"holdout:{line_no} is not an object")
        manual_class = payload.get("generator_class")
        body = payload.get("text")
        if not isinstance(manual_class, str) or not isinstance(body, str):
            raise ValueError(f"holdout:{line_no} is missing text or generator_class")
        rule_class = rule_class_for_labeled_text(text=body, manual_class=manual_class)
        if rule_class != manual_class:
            mismatches.append(
                HoldoutMismatch(
                    line_no=line_no,
                    manual_class=manual_class,
                    rule_class=rule_class,
                    text_preview=body[:80],
                )
            )
    mismatch_rows = tuple(mismatches)
    digest = hashlib.sha256(holdout_bytes).hexdigest()
    return HoldoutGateResult(
        ok=digest == expected_sha256 and rows == expected_rows and not mismatch_rows,
        rows=rows,
        sha256=digest,
        mismatches=mismatch_rows,
    )


def mean_metric(
    scores: Sequence[MarkerScore],
    name: Literal["retrieval_recall", "faithfulness", "answer_coverage"],
) -> float:
    if name not in _METRIC_NAMES:
        raise ValueError(f"unknown metric {name}")
    if not scores:
        raise ValueError("metric mean requires scores")
    return sum(float(getattr(score, name)) for score in scores) / len(scores)


def accept_h1(
    *,
    bugs_h0: Sequence[MarkerScore],
    bugs_h1: Sequence[MarkerScore],
) -> H1Acceptance:
    """Accept H1 from the bug slice and marker scores only.

    Must-not is cleared when every H1 answer has an empty hit list. Faithfulness
    and retrieval recall did not regress when ``mean(H1) + 1e-9 >= mean(H0)``.
    Accepted means those three conditions. Features are not part of the decision.
    """

    cleared = bool(bugs_h1) and all(not score.must_not_hits for score in bugs_h1)
    already_clear = bool(bugs_h0) and all(not score.must_not_hits for score in bugs_h0)
    faithfulness_ok = (
        mean_metric(bugs_h1, "faithfulness") + REGRESSION_EPSILON
        >= mean_metric(bugs_h0, "faithfulness")
    )
    recall_ok = (
        mean_metric(bugs_h1, "retrieval_recall") + REGRESSION_EPSILON
        >= mean_metric(bugs_h0, "retrieval_recall")
    )
    return H1Acceptance(
        bugs_must_not_cleared=cleared,
        bugs_must_not_hit_runs_h0=sum(1 for score in bugs_h0 if score.must_not_hits),
        bugs_must_not_hit_runs_h1=sum(1 for score in bugs_h1 if score.must_not_hits),
        bugs_must_not_already_clear_in_h0=already_clear,
        faithfulness_not_regressed=faithfulness_ok,
        retrieval_recall_not_regressed=recall_ok,
        accepted=cleared and faithfulness_ok and recall_ok,
    )


def h2_note(
    *,
    bugs_h1_sources: Sequence[Sequence[RetrievedSource]],
    expected_scenario_ids: Sequence[str],
    top_k: int,
) -> dict[str, object]:
    """Report whether repeated scenarios, not the k ceiling, hid a gold bug id.

    ``implemented`` is always false. ``needed`` is true only when some gold id is
    missing from all H1 searches and every search has fewer unique scenario ids
    than ``min(top_k, |gold|)``. Five distinct topics at k=5 is the k ceiling.
    """

    expected = _unique_expected(expected_scenario_ids) if expected_scenario_ids else ()
    capacity = min(top_k, len(expected))
    unique_counts: list[int] = []
    found: set[str] = set()
    for sources in bugs_h1_sources:
        scenario_ids = _unique_scenario_ids(sources)
        unique_counts.append(len(scenario_ids))
        found.update(scenario_ids)
    never_found = [scenario_id for scenario_id in expected if scenario_id not in found]
    mean_unique = sum(unique_counts) / len(unique_counts) if unique_counts else 0.0
    repeated = bool(unique_counts) and all(count < capacity for count in unique_counts)
    needed = bool(never_found) and repeated
    if needed:
        reason = _H2_REPEAT_REASON
    elif never_found:
        reason = _H2_K_CAP_REASON
    else:
        reason = ""
    return {
        "implemented": False,
        "needed": needed,
        "reason": reason,
        "never_found": never_found,
        "mean_unique_scenarios": mean_unique,
        "capacity": capacity,
    }


def _gold_question(
    item: object,
    *,
    question_id: str,
    slice_name: str,
    must_not: tuple[str, ...],
) -> GoldQuestion:
    if not isinstance(item, dict):
        raise ValueError("gold question is not an object")
    if item.get("question_id") != question_id or item.get("slice") != slice_name:
        raise ValueError(f"gold question must be {question_id}/{slice_name}")
    question = item.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"{question_id} question is empty")
    expected = _string_tuple(item.get("expected_scenario_ids"), field=f"{question_id}.expected_scenario_ids")
    if question_id == "critical_bugs":
        return GoldQuestion(
            question_id="critical_bugs",
            slice="bug",
            question=question,
            expected_scenario_ids=expected,
            must_not=must_not,
        )
    return GoldQuestion(
        question_id="requested_features",
        slice="feature",
        question=question,
        expected_scenario_ids=expected,
        must_not=must_not,
    )


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return tuple(value)


def _scenario_set(value: object, *, field: str) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} is not a list")
    found: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field} contains a non-string")
        found.add(item)
    return found


def _unique_expected(expected: Sequence[str]) -> tuple[str, ...]:
    if len(expected) == 0:
        raise ValueError("expected scenario ids are empty")
    unique = tuple(dict.fromkeys(scenario_id for scenario_id in expected if scenario_id))
    if not unique:
        raise ValueError("expected scenario ids are empty")
    return unique


def _unique_scenario_ids(sources: Sequence[RetrievedSource]) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for source in sources:
        scenario_id = source.scenario_id
        if not scenario_id or scenario_id in seen:
            continue
        seen.add(scenario_id)
        found.append(scenario_id)
    return tuple(found)


def _judge_score(payload: Mapping[str, Any]) -> JudgeScore | None:
    required = ("faithfulness", "answer_coverage", "must_not_present", "scenario_ids")
    if any(key not in payload for key in required):
        return None
    faithfulness = _unit_interval(payload["faithfulness"])
    coverage = _unit_interval(payload["answer_coverage"])
    present = payload["must_not_present"]
    scenario_ids = payload["scenario_ids"]
    if faithfulness is None or coverage is None or not isinstance(present, bool):
        return None
    if not isinstance(scenario_ids, list) or any(not isinstance(item, str) for item in scenario_ids):
        return None
    return JudgeScore(
        faithfulness=faithfulness,
        answer_coverage=coverage,
        must_not_present=present,
        scenario_ids=tuple(scenario_ids),
    )


def _unit_interval(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        return None
    return number

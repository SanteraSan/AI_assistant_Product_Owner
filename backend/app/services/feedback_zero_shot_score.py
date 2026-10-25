"""Zero-shot class scores and the QLoRA gate for feedback stage 7.

No network, Ollama, Qdrant, or Postgres. The lexicon normalizer is the same
function the rules use. This module does not decide ``index_in_rag`` and does
not start training.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.services.feedback_rules import normalize_lexicon_key

CLASS_ORDER: tuple[str, ...] = ("noise", "churn_signal", "bug", "feature")
STRATUM_PER_CLASS: int = 8
STRATUM_SEED: str = "feedback-v1-stage7-20261025"
CONTEST_REASON: str = (
    "Правила написаны под шаблоны этого jsonl и сохраняют generator_class, "
    "если фраза в своём лексиконе. Accuracy правил здесь победой не считается."
)
CLOSED_GATE_SENTENCE: str = "базовой модели и правил хватило"
_QLORA_CRITERION = "at least one holdout row where lexicon_rule_class != generator_class"
_UNPARSED = "unparsed"
_MISSING = object()


@dataclass(frozen=True)
class ParsedFeedbackClass:
    predicted_class: str | None
    parse_error: str | None


@dataclass(frozen=True)
class StratifiedRow:
    corpus_id: str
    generator_class: str
    scenario_id: str | None
    text: str
    source_file: str
    source_line: int


@dataclass(frozen=True)
class StratifiedSlice:
    rows: tuple[StratifiedRow, ...]
    per_class: int
    seed: str
    shortfall: dict[str, int]


@dataclass(frozen=True)
class ClassScore:
    support: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class SplitScore:
    rows: int
    accuracy: float
    macro_f1: float
    per_class: dict[str, ClassScore]
    confusion: dict[str, dict[str, int]]
    unparsed: int


@dataclass(frozen=True)
class QloraGate:
    open: bool
    mismatch_count: int
    criterion: str
    training_started: bool


def parse_feedback_class_response(raw: str) -> ParsedFeedbackClass:
    """Read the first JSON object's ``class`` label. ``thinking`` is not an input."""

    text = _prepare_class_text(raw)
    if text == "":
        return ParsedFeedbackClass(predicted_class=None, parse_error="empty")
    payload = _first_json_value(text)
    if payload is _MISSING:
        return ParsedFeedbackClass(predicted_class=None, parse_error="invalid_json")
    if not isinstance(payload, dict):
        return ParsedFeedbackClass(predicted_class=None, parse_error="not_object")
    if "class" not in payload:
        return ParsedFeedbackClass(predicted_class=None, parse_error="missing_class")
    label = payload["class"]
    if not isinstance(label, str):
        return ParsedFeedbackClass(predicted_class=None, parse_error="class_not_string")
    label = label.strip()
    if label not in CLASS_ORDER:
        return ParsedFeedbackClass(predicted_class=None, parse_error="unknown_class")
    return ParsedFeedbackClass(predicted_class=label, parse_error=None)


def select_stratified_rows(
    cleaned_rows: Sequence[Mapping[str, Any]],
    *,
    holdout_texts: Sequence[str],
    per_class: int = STRATUM_PER_CLASS,
    seed: str = STRATUM_SEED,
) -> StratifiedSlice:
    """Equal quota per class. Rank is sha256 of the seed and corpus id, not random.

    Rows come back in class order, and inside a class by rank. Exact duplicates,
    labels outside the four classes, and phrases whose normalized key is on the
    holdout are left out. Identical phrases inside one class keep the smaller
    ``corpus_id``.
    """

    if isinstance(per_class, bool) or not isinstance(per_class, int) or per_class < 0:
        raise ValueError("per_class must be an int >= 0")
    holdout_keys = {normalize_lexicon_key(text) for text in holdout_texts}
    by_class: dict[str, dict[str, StratifiedRow]] = {name: {} for name in CLASS_ORDER}
    for row in cleaned_rows:
        if not isinstance(row, Mapping):
            continue
        parsed = _candidate_row(row, holdout_keys)
        if parsed is None:
            continue
        key = normalize_lexicon_key(parsed.text)
        current = by_class[parsed.generator_class].get(key)
        if current is None or parsed.corpus_id < current.corpus_id:
            by_class[parsed.generator_class][key] = parsed
    selected: list[StratifiedRow] = []
    shortfall: dict[str, int] = {}
    for class_name in CLASS_ORDER:
        ranked = sorted(
            by_class[class_name].values(),
            key=lambda item: (_stratum_rank(seed, item.corpus_id), item.corpus_id),
        )
        if len(ranked) < per_class:
            shortfall[class_name] = per_class - len(ranked)
        selected.extend(ranked[:per_class])
    return StratifiedSlice(
        rows=tuple(selected),
        per_class=per_class,
        seed=seed,
        shortfall=shortfall,
    )


def score_predictions(
    golds: Sequence[str],
    predictions: Sequence[str | None],
) -> SplitScore:
    """Accuracy and macro-F1 over the four classes. Unparsed predictions are not a class."""

    if len(golds) != len(predictions):
        raise ValueError("golds and predictions have different lengths")
    for gold in golds:
        if gold not in CLASS_ORDER:
            raise ValueError(f"gold class {gold!r} is outside the four classes")
    support = {name: 0 for name in CLASS_ORDER}
    true_positive = {name: 0 for name in CLASS_ORDER}
    false_positive = {name: 0 for name in CLASS_ORDER}
    false_negative = {name: 0 for name in CLASS_ORDER}
    confusion = {
        gold: {predicted: 0 for predicted in (*CLASS_ORDER, _UNPARSED)} for gold in CLASS_ORDER
    }
    correct = 0
    unparsed = 0
    for gold, predicted in zip(golds, predictions, strict=True):
        support[gold] += 1
        if predicted is None:
            unparsed += 1
            confusion[gold][_UNPARSED] += 1
        elif predicted in CLASS_ORDER:
            confusion[gold][predicted] += 1
        if predicted == gold:
            correct += 1
        for class_name in CLASS_ORDER:
            if gold == class_name and predicted == class_name:
                true_positive[class_name] += 1
            elif gold != class_name and predicted == class_name:
                false_positive[class_name] += 1
            elif gold == class_name and predicted != class_name:
                false_negative[class_name] += 1
    per_class: dict[str, ClassScore] = {}
    for class_name in CLASS_ORDER:
        precision = _ratio(true_positive[class_name], true_positive[class_name] + false_positive[class_name])
        recall = _ratio(true_positive[class_name], true_positive[class_name] + false_negative[class_name])
        per_class[class_name] = ClassScore(
            support=support[class_name],
            tp=true_positive[class_name],
            fp=false_positive[class_name],
            fn=false_negative[class_name],
            precision=precision,
            recall=recall,
            f1=_f1(precision, recall),
        )
    rows = len(golds)
    return SplitScore(
        rows=rows,
        accuracy=(correct / rows) if rows else 0.0,
        macro_f1=sum(item.f1 for item in per_class.values()) / len(CLASS_ORDER),
        per_class=per_class,
        confusion=confusion,
        unparsed=unparsed,
    )


def decide_qlora_gate(mismatch_count: int) -> QloraGate:
    """One holdout mismatch opens the gate. Model scores are not an input."""

    if isinstance(mismatch_count, bool) or not isinstance(mismatch_count, int):
        raise ValueError("mismatch_count must be an int")
    if mismatch_count < 0:
        raise ValueError("mismatch_count must be >= 0")
    return QloraGate(
        open=mismatch_count >= 1,
        mismatch_count=mismatch_count,
        criterion=_QLORA_CRITERION,
        training_started=False,
    )


def holdout_agreement(
    golds: Sequence[str],
    rule_classes: Sequence[str],
    predictions: Sequence[str | None],
) -> dict[str, int]:
    """Rules against zero-shot on the holdout. Unparsed rows stay inside the four-way split."""

    if not (len(golds) == len(rule_classes) == len(predictions)):
        raise ValueError("agreement inputs have different lengths")
    both_correct = 0
    rules_only = 0
    zero_shot_only = 0
    both_wrong = 0
    zero_shot_unparsed = 0
    for gold, rule_class, predicted in zip(golds, rule_classes, predictions, strict=True):
        rules_ok = rule_class == gold
        model_ok = predicted == gold
        if rules_ok and model_ok:
            both_correct += 1
        elif rules_ok:
            rules_only += 1
        elif model_ok:
            zero_shot_only += 1
        else:
            both_wrong += 1
        if predicted is None:
            zero_shot_unparsed += 1
    return {
        "both_correct": both_correct,
        "rules_only": rules_only,
        "zero_shot_only": zero_shot_only,
        "both_wrong": both_wrong,
        "zero_shot_unparsed": zero_shot_unparsed,
    }


def render_journal_decision(
    *,
    gate: QloraGate,
    holdout_rules_macro_f1: float,
    holdout_zero_shot_macro_f1: float,
    zero_shot_only: int,
) -> str:
    """Closed gate keeps the baseline sentence. An open gate does not start training."""

    rules_f1 = f"{holdout_rules_macro_f1:.4f}"
    zero_shot_f1 = f"{holdout_zero_shot_macro_f1:.4f}"
    metrics = (
        f"macro-F1 правил на holdout {rules_f1}, "
        f"macro-F1 zero-shot на holdout {zero_shot_f1}, "
        f"zero_shot_only {zero_shot_only}."
    )
    if gate.open:
        return (
            "Ворота QLoRA открыты: правила разошлись с ручной меткой на "
            f"{gate.mismatch_count} строках holdout. "
            "Обучение в этом заходе не запускалось. "
            "Следующий заход — отдельный скрипт, не воркер индексации. "
            f"{metrics}"
        )
    return (
        f"qlora_gate.open false, mismatch_count {gate.mismatch_count}. "
        f"{CLOSED_GATE_SENTENCE}. "
        "Фраза значит, что обучение не стартует. Она не значит, что zero-shot угадал все строки. "
        f"{metrics} "
        "При нуле расхождений правил модель не может быть строго лучше правил на holdout. "
        "Адаптера нет, воркер индексации не менялся, training_started false."
    )


def _prepare_class_text(raw: str) -> str:
    text = raw.strip().lstrip("\ufeff").strip()
    if text.startswith("<think>") and "</think>" in text:
        end = text.find("</think>")
        text = text[end + len("</think>") :].strip()
    if text.startswith("```"):
        lines = text.splitlines()
        body = lines[1:]
        if body and body[-1].strip().startswith("```"):
            body = body[:-1]
        text = "\n".join(body).strip()
    return text


def _first_json_value(text: str) -> object:
    """First object, like the summary judge. A bare non-object is returned as-is."""

    decoder = json.JSONDecoder()
    start = 0
    while start < len(text):
        brace = text.find("{", start)
        if brace < 0:
            break
        try:
            payload, _end = decoder.raw_decode(text[brace:])
        except json.JSONDecodeError:
            start = brace + 1
            continue
        return payload
    try:
        payload, _end = decoder.raw_decode(text)
    except json.JSONDecodeError:
        return _MISSING
    return payload


def _candidate_row(
    row: Mapping[str, Any],
    holdout_keys: set[str],
) -> StratifiedRow | None:
    if row.get("is_exact_duplicate") is not False:
        return None
    generator_class = row.get("generator_class")
    text = row.get("text")
    corpus_id = row.get("corpus_id")
    if generator_class not in CLASS_ORDER:
        return None
    if not isinstance(text, str) or not isinstance(corpus_id, str) or not corpus_id:
        return None
    if normalize_lexicon_key(text) in holdout_keys:
        return None
    scenario_id = row.get("scenario_id")
    if scenario_id is not None and not isinstance(scenario_id, str):
        return None
    source_file = row.get("source_file")
    source_line = row.get("source_line")
    return StratifiedRow(
        corpus_id=corpus_id,
        generator_class=str(generator_class),
        scenario_id=scenario_id,
        text=text,
        source_file=source_file if isinstance(source_file, str) else "",
        source_line=_source_line(source_line),
    )


def _source_line(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _stratum_rank(seed: str, corpus_id: str) -> str:
    return hashlib.sha256(f"{seed}\n{corpus_id}".encode("utf-8")).hexdigest()


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)

"""Stage 7 zero-shot parsing, scores, stratum, and the QLoRA gate.

No Ollama, no QLoRA, and no writes to the live eval report or the frozen
jsonl. Protocol failures are pointed at temporary files. ``main`` is not
called on the live corpus.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import random
import re
from pathlib import Path

import pytest

from app.services.feedback_zero_shot_score import (
    CLASS_ORDER,
    decide_qlora_gate,
    parse_feedback_class_response,
    render_journal_decision,
    score_predictions,
    select_stratified_rows,
)
import scripts.eval_feedback_zero_shot as eval_zero_shot

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_DIR = REPO_ROOT / "data" / "feedback" / "v1"
HOLDOUT_PATH = V1_DIR / "holdout.jsonl"
CLEANED_PATH = V1_DIR / "cleaned.jsonl"
EVAL_PATH = REPO_ROOT / "research" / "feedback_zero_shot_eval_latest.json"
PROMPT_PATH = REPO_ROOT / "research" / "prompts" / "feedback_zero_shot_class.txt"
PROTECTED_PATHS = (HOLDOUT_PATH, CLEANED_PATH, EVAL_PATH)
FLAG_ERROR = "Flag must be --model qwen3.8:latest"
EXAMPLE_PHRASES = ("Класс!", "Удаляю", "Ниче не работает")
STRATUM_SEED = "stage7-fixture-seed"
LONG_TEXT = "длинный префикс " * 400


@pytest.fixture(autouse=True)
def _live_files_stay_byte_for_byte() -> None:
    before = {path: path.read_bytes() for path in PROTECTED_PATHS}
    yield
    for path, data in before.items():
        assert path.read_bytes() == data, f"{path.relative_to(REPO_ROOT).as_posix()} changed during the test"


def _number_token(text: str, number: str) -> bool:
    return re.search(rf"(?<![0-9.]){re.escape(number)}(?![0-9])", text) is not None


def _jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        assert isinstance(payload, dict)
        rows.append(payload)
    return rows


def _rank(seed: str, corpus_id: str) -> str:
    return hashlib.sha256(f"{seed}\n{corpus_id}".encode("utf-8")).hexdigest()


def _row(
    corpus_id: str,
    generator_class: str,
    text: str,
    *,
    exact: bool = False,
) -> dict[str, object]:
    return {
        "corpus_id": corpus_id,
        "generator_class": generator_class,
        "text": text,
        "is_exact_duplicate": exact,
        "scenario_id": "fixture",
        "source_file": "fixture",
        "source_line": 1,
    }


def _forbid_random(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("random must not be used")

    for name in ("random", "randrange", "randint", "choice", "choices", "sample", "shuffle"):
        monkeypatch.setattr(random, name, _boom)


def _assert_score_module_does_not_import_random() -> None:
    tree = ast.parse(inspect.getsource(inspect.getmodule(select_stratified_rows)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
            assert "random" not in imported
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "random"


def _forbid_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("model check must return before protocol load or generation")

    monkeypatch.setattr(eval_zero_shot, "_prepare", _forbidden)
    monkeypatch.setattr(eval_zero_shot, "_evaluate", _forbidden)
    monkeypatch.setattr(eval_zero_shot, "OllamaClient", _forbidden)


def _isolate_protocol(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    holdout: bytes,
    manifest_sha: str,
    cleaned: bytes,
) -> None:
    holdout_path = tmp_path / "holdout.jsonl"
    manifest_path = tmp_path / "manifest.json"
    cleaned_path = tmp_path / "cleaned.jsonl"
    prompt_path = tmp_path / "prompt.txt"
    output_path = tmp_path / "out.json"
    holdout_path.write_bytes(holdout)
    manifest_path.write_text(
        json.dumps({"holdout_sha256": manifest_sha}),
        encoding="utf-8",
    )
    cleaned_path.write_bytes(cleaned)
    prompt_path.write_text("Обращение:\n{text}\n", encoding="utf-8")
    monkeypatch.setattr(eval_zero_shot, "_HOLDOUT_PATH", holdout_path)
    monkeypatch.setattr(eval_zero_shot, "_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(eval_zero_shot, "_CLEANED_PATH", cleaned_path)
    monkeypatch.setattr(eval_zero_shot, "_PROMPT_FILE", prompt_path)
    monkeypatch.setattr(eval_zero_shot, "_OUTPUT_PATH", output_path)

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("generation must not run")

    monkeypatch.setattr(eval_zero_shot, "_evaluate", _forbidden)
    monkeypatch.setattr(eval_zero_shot, "OllamaClient", _forbidden)


def _holdout_bytes(rows: int) -> bytes:
    line = json.dumps({"text": "x", "generator_class": "noise"}, ensure_ascii=False) + "\n"
    return (line * rows).encode("utf-8")


@pytest.mark.parametrize(
    ("raw", "predicted"),
    [
        pytest.param('{"class":"bug"}', "bug", id="bare-json"),
        pytest.param('{"class":"feature","why":"extra"}', "feature", id="extra-keys"),
        pytest.param('итог {"class": "noise"} конец', "noise", id="text-around-json"),
        pytest.param(LONG_TEXT + '{"class":"bug"}' + LONG_TEXT, "bug", id="long-text"),
        pytest.param('```json\n{"class": "churn_signal"}\n```', "churn_signal", id="markdown-fence"),
        pytest.param("", None, id="empty"),
        pytest.param("[]", None, id="not-object-array"),
        pytest.param('"bug"', None, id="not-object-string"),
        pytest.param('{"label":"bug"}', None, id="missing-class"),
        pytest.param('{"class":"баг"}', None, id="cyrillic-bug"),
        pytest.param('{"class":"Noise"}', None, id="capital-noise"),
        pytest.param('{"class":" noise "}', "noise", id="stripped-noise"),
        pytest.param('{"class":"bug"} {"class":"feature"}', "bug", id="first-of-two-objects"),
        pytest.param(
            '<think>{"class":"bug"}</think>{"class":"feature"}',
            "feature",
            id="think-block-removed",
        ),
    ],
)
def test_parse_feedback_class_response(raw: str, predicted: str | None) -> None:
    """The parser reads one response string. thinking is not a separate argument."""

    assert list(inspect.signature(parse_feedback_class_response).parameters) == ["raw"]
    parsed = parse_feedback_class_response(raw)
    assert parsed.predicted_class == predicted
    if predicted is None:
        assert parsed.parse_error
    else:
        assert parsed.parse_error is None


def test_score_predictions_control_example_macro_f1_is_one_third() -> None:
    """noise, None, bug, bug against noise, noise, bug, feature scores 1/3 and 0.5."""

    score = score_predictions(
        ["noise", "noise", "bug", "feature"],
        ["noise", None, "bug", "bug"],
    )
    assert score.macro_f1 == 1 / 3
    assert score.accuracy == 0.5
    assert score.unparsed == 1
    assert score.confusion["noise"]["unparsed"] == 1
    assert score.per_class["noise"].fn == 1


def test_score_predictions_perfect_four_classes_macro_f1_is_one() -> None:
    golds = list(CLASS_ORDER)
    score = score_predictions(golds, golds)
    assert score.macro_f1 == 1.0


def test_score_predictions_rejects_length_mismatch_and_unknown_gold() -> None:
    with pytest.raises(ValueError, match="different lengths"):
        score_predictions(["noise", "bug"], ["noise"])
    with pytest.raises(ValueError, match="outside the four classes"):
        score_predictions(["praise"], [None])


def test_select_stratified_rows_fixture_is_stable_without_random() -> None:
    """Same seed, same ids. Copies, the holdout key, and the larger duplicate id drop out."""

    rows = [
        _row("dup-b", "noise", "повторяющаяся фраза stage7"),
        _row("dup-a", "noise", "  ПОВТОРЯЮЩАЯСЯ   фраза   stage7 "),
        _row("exact-bug", "bug", "точная копия бага", exact=True),
        _row("bug-1", "bug", "баг номер один"),
        _row("bug-2", "bug", "баг номер два"),
        _row("churn-1", "churn_signal", "сигнал один"),
        _row("churn-2", "churn_signal", "сигнал два"),
        _row("feature-hold", "feature", "Уникальная фраза holdout stage7"),
        _row("feature-1", "feature", "фича номер один"),
        _row("feature-2", "feature", "фича номер два"),
    ]
    holdout = ["  уникальная   ФРАЗА   holdout   stage7 "]
    _assert_score_module_does_not_import_random()
    first = select_stratified_rows(rows, holdout_texts=holdout, per_class=2, seed=STRATUM_SEED)
    second = select_stratified_rows(
        list(reversed(rows)),
        holdout_texts=holdout,
        per_class=2,
        seed=STRATUM_SEED,
    )
    first_ids = [row.corpus_id for row in first.rows]
    assert first_ids == [row.corpus_id for row in second.rows]
    selected = set(first_ids)
    assert "dup-a" in selected
    assert "dup-b" not in selected
    assert "exact-bug" not in selected
    assert "feature-hold" not in selected
    classes = [row.generator_class for row in first.rows]
    assert classes == [name for name in CLASS_ORDER for _ in range(classes.count(name))]
    assert set(classes) == set(CLASS_ORDER)
    for name in CLASS_ORDER:
        group = [row.corpus_id for row in first.rows if row.generator_class == name]
        assert group == sorted(group, key=lambda corpus_id: (_rank(STRATUM_SEED, corpus_id), corpus_id))


def test_select_stratified_rows_does_not_call_random(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        _row("dup-a", "noise", "одна фраза"),
        _row("dup-b", "noise", "одна фраза"),
        _row("churn-1", "churn_signal", "сигнал"),
        _row("bug-1", "bug", "поломка"),
        _row("feature-1", "feature", "просьба"),
    ]
    _forbid_random(monkeypatch)
    chosen = select_stratified_rows(rows, holdout_texts=[], per_class=1, seed=STRATUM_SEED)
    assert [row.corpus_id for row in chosen.rows if row.generator_class == "noise"] == ["dup-a"]


def test_live_stratum_is_balanced_and_holdout_bytes_stay() -> None:
    holdout_before = HOLDOUT_PATH.read_bytes()
    cleaned_before = CLEANED_PATH.read_bytes()
    holdout = _jsonl(HOLDOUT_PATH)
    cleaned = _jsonl(CLEANED_PATH)
    support = {name: 0 for name in CLASS_ORDER}
    for row in holdout:
        label = row["generator_class"]
        assert isinstance(label, str)
        support[label] += 1
    assert support == {"noise": 4, "churn_signal": 3, "bug": 7, "feature": 6}
    texts = [row["text"] for row in holdout]
    assert all(isinstance(text, str) for text in texts)
    first = select_stratified_rows(cleaned, holdout_texts=texts)  # type: ignore[arg-type]
    second = select_stratified_rows(cleaned, holdout_texts=texts)  # type: ignore[arg-type]
    assert len(first.rows) == 32
    assert first.shortfall == {}
    assert [row.generator_class for row in first.rows] == [
        name for name in CLASS_ORDER for _index in range(8)
    ]
    assert [row.corpus_id for row in first.rows] == [row.corpus_id for row in second.rows]
    assert HOLDOUT_PATH.read_bytes() == holdout_before
    assert CLEANED_PATH.read_bytes() == cleaned_before


def test_decide_qlora_gate_opens_on_a_mismatch_and_does_not_train() -> None:
    """Zero-shot errors are not an input. The signature is only mismatch_count."""

    assert list(inspect.signature(decide_qlora_gate).parameters) == ["mismatch_count"]
    closed = decide_qlora_gate(0)
    opened = decide_qlora_gate(1)
    assert closed.open is False
    assert opened.open is True
    assert closed.training_started is False
    assert opened.training_started is False
    with pytest.raises(ValueError, match="mismatch_count must be >= 0"):
        decide_qlora_gate(-1)


def test_render_journal_decision_closed_sentence_and_open_training() -> None:
    rules_f1 = 1 / 3
    zero_shot_f1 = 0.9285714285714286
    closed = render_journal_decision(
        gate=decide_qlora_gate(0),
        holdout_rules_macro_f1=rules_f1,
        holdout_zero_shot_macro_f1=zero_shot_f1,
        zero_shot_only=0,
    )
    assert "базовой модели и правил хватило" in closed
    assert _number_token(closed, f"{rules_f1:.4f}")
    assert _number_token(closed, f"{zero_shot_f1:.4f}")
    opened = render_journal_decision(
        gate=decide_qlora_gate(1),
        holdout_rules_macro_f1=rules_f1,
        holdout_zero_shot_macro_f1=zero_shot_f1,
        zero_shot_only=1,
    )
    assert "базовой модели и правил хватило" not in opened
    assert "не запускалось" in opened


def test_zero_shot_prompt_has_one_slot_and_no_holdout_or_examples() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    assert prompt.count("{text}") == 1
    assert prompt.count("Обращение:") == 1
    for phrase in EXAMPLE_PHRASES:
        assert phrase not in prompt, f"prompt contains example {phrase!r}"
    assert re.search(r"(?i)(?<![\w])ок(?![\w])", prompt) is None
    for row in _jsonl(HOLDOUT_PATH):
        text = row["text"]
        assert isinstance(text, str) and text.strip()
        assert text not in prompt, "prompt contains a holdout row"


@pytest.mark.parametrize("model", ["qwen3.8:latest", "  qwen3.8:latest\n", "\tqwen3.8:latest  "])
def test_assert_chat_model_accepts_only_qwen38_after_strip(model: str) -> None:
    eval_zero_shot.assert_chat_model(model)


@pytest.mark.parametrize("model", ["qwen3.5:9b", "", "  qwen3.5:9b"])
def test_assert_chat_model_rejects_other_models(
    model: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected model is SystemExit 2, and main prints the flag sentence before any load."""

    _forbid_generation(monkeypatch)
    with pytest.raises(SystemExit) as caught:
        eval_zero_shot.assert_chat_model(model)
    assert caught.value.code == 2
    code = eval_zero_shot.main(["--model", model])
    assert code == 2
    assert FLAG_ERROR in capsys.readouterr().err


def test_protocol_exits_2_on_broken_corpus_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    holdout = _holdout_bytes(20)
    _isolate_protocol(
        monkeypatch,
        tmp_path,
        holdout=holdout,
        manifest_sha=hashlib.sha256(holdout).hexdigest(),
        cleaned=b'{"corpus_id": \n',
    )
    code = eval_zero_shot.main(["--model", "qwen3.8:latest"])
    error = capsys.readouterr().err
    assert code == 2
    assert FLAG_ERROR not in error
    assert "Expecting" in error


def test_protocol_exits_2_when_holdout_sha_is_not_in_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    holdout = _holdout_bytes(20)
    _isolate_protocol(
        monkeypatch,
        tmp_path,
        holdout=holdout,
        manifest_sha="0" * 64,
        cleaned=b"",
    )
    code = eval_zero_shot.main(["--model", "qwen3.8:latest"])
    error = capsys.readouterr().err
    assert code == 2
    assert "does not match manifest holdout_sha256" in error


def test_protocol_exits_2_when_holdout_is_not_20_rows(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    holdout = _holdout_bytes(19)
    _isolate_protocol(
        monkeypatch,
        tmp_path,
        holdout=holdout,
        manifest_sha=hashlib.sha256(holdout).hexdigest(),
        cleaned=b"",
    )
    code = eval_zero_shot.main(["--model", "qwen3.8:latest"])
    error = capsys.readouterr().err
    assert code == 2
    assert "expected 20" in error

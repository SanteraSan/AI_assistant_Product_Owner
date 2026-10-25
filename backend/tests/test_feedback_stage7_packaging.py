"""Stage 7 packaging of the already computed zero-shot measurement.

Reads the eval JSON, the lessons journal, the backend README, and the RAG
checklist. Does not call Ollama, start QLoRA, or rewrite the report.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_PATH = REPO_ROOT / "research" / "feedback_zero_shot_eval_latest.json"
JOURNAL_PATH = REPO_ROOT / "research" / "LESSONS_LEARNED.md"
README_PATH = REPO_ROOT / "backend" / "README.md"
CHECKLIST_PATH = REPO_ROOT / "research" / "RAG_EVALUATION_CHECKLIST.md"
STAGE7_HEADING = "## 2026-10-25: Этап 7 — zero-shot классы фидбека"
STAGE4_HEADING = "## 2026-10-25: Замер саммари фидбека H0/H1"
EVAL_COMMAND = "python backend/scripts/eval_feedback_zero_shot.py --model qwen3.8:latest"
CLOSED_GATE_SENTENCE = "базовой модели и правил хватило"
SCORE_SPLITS = ("holdout", "stratified")
SCORE_ARMS = ("rules", "zero_shot")


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path.relative_to(REPO_ROOT).as_posix()}"
    return path.read_text(encoding="utf-8")


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(_read(path))
    assert isinstance(payload, dict)
    return payload


def _span(lines: list[str], heading: str) -> tuple[int, int]:
    starts = [index for index, line in enumerate(lines) if line.strip() == heading]
    assert len(starts) == 1, f"expected one {heading!r}, found {len(starts)}"
    start = starts[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return start, end


def _section(path: Path, heading: str) -> str:
    lines = _read(path).splitlines()
    start, end = _span(lines, heading)
    return "\n".join(lines[start:end])


def _number_token(text: str, number: str) -> bool:
    return re.search(rf"(?<![0-9.]){re.escape(number)}(?![0-9])", text) is not None


def _labeled_numbers(text: str, label: str) -> list[str]:
    return re.findall(rf"{re.escape(label)} ([0-9]+(?:\.[0-9]+)?)", text)


def test_stage7_heading_is_present() -> None:
    lines = _read(JOURNAL_PATH).splitlines()
    found = [line for line in lines if line.strip() == STAGE7_HEADING]
    assert found == [STAGE7_HEADING]


def test_readme_and_checklist_quote_the_zero_shot_command() -> None:
    assert EVAL_COMMAND in _read(README_PATH)
    assert EVAL_COMMAND in _read(CHECKLIST_PATH)


def test_eval_json_names_qwen38_and_does_not_start_training() -> None:
    report = _json(EVAL_PATH)
    assert report["model"] == "qwen3.8:latest"
    gate = report["qlora_gate"]
    assert isinstance(gate, dict)
    assert gate["training_started"] is False


def test_lora_adapter_is_not_a_completed_artifact() -> None:
    assert not (REPO_ROOT / "models" / "feedback_classifier_lora").exists()
    assert not (REPO_ROOT / "research" / "FEEDBACK_CLASSIFIER_LORA.md").exists()


def test_baseline_sentence_is_present_only_when_the_gate_is_closed() -> None:
    """The live JSON is not rewritten. The open-gate sentence is covered elsewhere."""

    report = _json(EVAL_PATH)
    gate = report["qlora_gate"]
    assert isinstance(gate, dict)
    open_gate = gate["open"]
    assert isinstance(open_gate, bool)
    section = _section(JOURNAL_PATH, STAGE7_HEADING)
    if open_gate:
        assert CLOSED_GATE_SENTENCE not in section
    else:
        assert CLOSED_GATE_SENTENCE in section


def test_journal_macro_f1_matches_json_four_decimals() -> None:
    report = _json(EVAL_PATH)
    scores = report["scores"]
    assert isinstance(scores, dict)
    section = _section(JOURNAL_PATH, STAGE7_HEADING)
    for split_name in SCORE_SPLITS:
        split = scores[split_name]
        assert isinstance(split, dict)
        for arm in SCORE_ARMS:
            block = split[arm]
            assert isinstance(block, dict)
            value = block["macro_f1"]
            assert isinstance(value, (int, float)) and not isinstance(value, bool)
            token = f"{float(value):.4f}"
            assert _number_token(section, token), (
                f"{split_name} {arm} macro-F1 {token} is missing from the stage 7 journal"
            )


def test_journal_shares_match_ollama_ps_last() -> None:
    """Shares come from this report's ollama_ps_last, formatted to two decimals."""

    report = _json(EVAL_PATH)
    ps_last = report["ollama_ps_last"]
    assert isinstance(ps_last, dict)
    gpu = ps_last["gpu_share"]
    cpu = ps_last["cpu_share"]
    context = ps_last["context_length"]
    assert isinstance(gpu, float) and not isinstance(gpu, bool)
    assert isinstance(cpu, float) and not isinstance(cpu, bool)
    assert isinstance(context, int) and not isinstance(context, bool)
    section = _section(JOURNAL_PATH, STAGE7_HEADING)
    expected = {
        "gpu_share": f"{gpu:.2f}",
        "cpu_share": f"{cpu:.2f}",
        "context_length": str(context),
    }
    for label, token in expected.items():
        found = _labeled_numbers(section, label)
        assert found, f"stage 7 journal has no {label} from ollama_ps_last"
        assert found == [token] * len(found), (
            f"journal {label} {found} != ollama_ps_last {token}"
        )


def test_h0h1_journal_record_does_not_contain_qlora() -> None:
    """Same span as the stage 4 packaging test: the H0/H1 heading until the next one."""

    section = _section(JOURNAL_PATH, STAGE4_HEADING)
    assert "QLoRA" not in section

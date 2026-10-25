"""Stage 4 packaging of the already computed feedback summary measurement.

Reads the eval JSON, the lessons journal, the backend README, the RAG
checklist, and the v1 manifest. Does not run the H0/H1 scorer, open
Postgres, call Ollama, or talk HTTP.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_PATH = REPO_ROOT / "research" / "feedback_summary_eval_latest.json"
JOURNAL_PATH = REPO_ROOT / "research" / "LESSONS_LEARNED.md"
README_PATH = REPO_ROOT / "backend" / "README.md"
CHECKLIST_PATH = REPO_ROOT / "research" / "RAG_EVALUATION_CHECKLIST.md"
MANIFEST_PATH = REPO_ROOT / "data" / "feedback" / "v1" / "manifest.json"

STAGE4_HEADING = "## 2026-10-25: Замер саммари фидбека H0/H1"
SEPTEMBER_HEADING_PREFIX = "## 2026-09-15:"
README_SUMMARY_HEADING = "### Замер саммари"
CHECKLIST_FEEDBACK_HEADING = "## Фидбек v1: саммари H0/H1"
CHECKLIST_TODO_HEADING = "## Open TODOs"

SUMMARY_CELLS = (
    ("critical_bugs", "H0"),
    ("critical_bugs", "H1"),
    ("requested_features", "H0"),
    ("requested_features", "H1"),
)
SUMMARY_METRICS = (
    "retrieval_recall_mean",
    "faithfulness_mean",
    "answer_coverage_mean",
    "must_not_hit_runs",
    "judge_faithfulness_mean",
    "judge_answer_coverage_mean",
)
SHARE_KEYS = ("noise", "churn_signal", "bug", "feature")

POSTGRES_REASON = (
    "Seed этапа 2 в рабочую Postgres не выполнялся. "
    "Знаменатель — counts манифеста, проверенные scroll коллекции feedback_eval_v1. "
    "Продуктовый бакет не засевается."
)
H2_REASON = "recall capped by k, not by repeated scenarios"
EVAL_COMMAND = "python backend/scripts/eval_feedback_summary.py"
EVAL_MODEL_FLAG = "--model qwen3.8:latest"
EVAL_EMBEDDING_FLAG = "--embedding-model nomic-embed-text"

REJECTED_PHRASES = (
    "не показал прирост фильтра",
    "по воротам плана не выиграл",
    "gpu_share",
    "qwen3.5:9b",
    "дообучили",
    "QLoRA",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path.relative_to(REPO_ROOT).as_posix()}"
    return path.read_text(encoding="utf-8")


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(_read(path))
    assert isinstance(payload, dict)
    return payload


def _stage4_span(lines: list[str]) -> tuple[int, int]:
    starts = [index for index, line in enumerate(lines) if line.strip() == STAGE4_HEADING]
    assert len(starts) == 1, f"expected one stage 4 heading, found {len(starts)}"
    start = starts[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return start, end


def _stage4_section(journal: str) -> str:
    lines = journal.splitlines()
    start, end = _stage4_span(lines)
    return "\n".join(lines[start:end])


def _markdown_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == heading]
    assert len(starts) == 1, f"expected one {heading!r}, found {len(starts)}"
    start = starts[0]
    level = _heading_level(lines[start])
    assert level is not None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        marked = _heading_level(lines[index])
        if marked is not None and marked <= level:
            end = index
            break
    return "\n".join(lines[start:end])


def _heading_level(line: str) -> int | None:
    stripped = line.strip()
    marks = 0
    for char in stripped:
        if char != "#":
            break
        marks += 1
    if marks == 0 or marks >= len(stripped) or stripped[marks] != " ":
        return None
    return marks


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _summary_table(section: str) -> dict[tuple[str, str], dict[str, str]]:
    lines = section.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip().startswith("|"):
            index += 1
            continue
        block: list[str] = []
        while index < len(lines) and lines[index].strip().startswith("|"):
            block.append(lines[index])
            index += 1
        header = _cells(block[0])
        rows = [cells for line in block[1:] if not _is_separator(cells := _cells(line))]
        tables.append((header, rows))
    matched = [table for table in tables if "retrieval_recall_mean" in table[0]]
    assert len(matched) == 1, f"expected one summary table, found {len(matched)}"
    header, rows = matched[0]
    column = {name: position for position, name in enumerate(header)}
    for name in ("срез", "рука", *SUMMARY_METRICS):
        assert name in column, f"summary table missing column {name}"
    parsed: dict[tuple[str, str], dict[str, str]] = {}
    for cells in rows:
        assert len(cells) == len(header), f"summary row has {len(cells)} cells, header has {len(header)}"
        key = (cells[column["срез"]], cells[column["рука"]])
        assert key not in parsed, f"duplicate summary row {key[0]} {key[1]}"
        parsed[key] = {metric: cells[column[metric]] for metric in SUMMARY_METRICS}
    return parsed


def _as_float(raw: str, slice_name: str, arm: str, metric: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise AssertionError(
            f"{slice_name} {arm} {metric}: journal cell {raw!r} is not a number"
        ) from exc


def _number_token(text: str, number: str) -> bool:
    # A sentence period may follow the token. Another digit may not.
    return re.search(rf"(?<![0-9.]){re.escape(number)}(?![0-9])", text) is not None


def _field_is_false(section: str, name: str) -> bool:
    return re.search(rf"`?{re.escape(name)}`?\s+false\b", section) is not None


def _eval_command(section: str) -> str:
    lines = section.splitlines()
    for index, line in enumerate(lines):
        if EVAL_COMMAND not in line:
            continue
        collected = [line]
        if line.rstrip().endswith("\\"):
            for follow in lines[index + 1 :]:
                collected.append(follow)
                if not follow.rstrip().endswith("\\"):
                    break
        return " ".join(" ".join(collected).replace("\\", " ").split())
    raise AssertionError(f"{EVAL_COMMAND} is missing")


def _phrase_hits(
    label: str,
    text: str,
    phrases: tuple[str, ...],
    *,
    first_line: int = 1,
) -> list[str]:
    hits: list[str] = []
    for phrase in phrases:
        for number, line in enumerate(text.splitlines(), start=first_line):
            if phrase not in line:
                continue
            snippet = line.strip()
            if len(snippet) > 180:
                snippet = snippet[:177] + "..."
            hits.append(f"{label} line {number}: {phrase!r} in {snippet}")
    return hits


def test_stage4_heading_is_unique_and_precedes_2026_09_15() -> None:
    lines = _read(JOURNAL_PATH).splitlines()
    stage4 = [index for index, line in enumerate(lines) if line.strip() == STAGE4_HEADING]
    september = [index for index, line in enumerate(lines) if line.startswith(SEPTEMBER_HEADING_PREFIX)]
    assert len(stage4) == 1, f"expected one {STAGE4_HEADING!r}, found {len(stage4)}"
    assert september, f"journal has no {SEPTEMBER_HEADING_PREFIX!r} heading"
    assert stage4[0] < september[0], (
        f"{STAGE4_HEADING!r} at line {stage4[0] + 1} is not before "
        f"{SEPTEMBER_HEADING_PREFIX!r} at line {september[0] + 1}"
    )


def test_journal_summary_table_matches_eval_json() -> None:
    report = _json(EVAL_PATH)
    summary = report["summary"]
    assert isinstance(summary, dict)
    for slice_name, arm in SUMMARY_CELLS:
        assert slice_name in summary, f"json summary missing {slice_name}"
        arms = summary[slice_name]
        assert isinstance(arms, dict)
        assert arm in arms, f"json summary missing {slice_name} {arm}"
    table = _summary_table(_stage4_section(_read(JOURNAL_PATH)))
    for slice_name, arms in summary.items():
        assert isinstance(arms, dict)
        for arm, metrics in arms.items():
            assert isinstance(metrics, dict)
            key = (str(slice_name), str(arm))
            assert key in table, f"journal summary table has no row for {slice_name} {arm}"
            for metric in SUMMARY_METRICS:
                assert metric in metrics, f"json summary {slice_name} {arm} missing {metric}"
                expected = metrics[metric]
                assert isinstance(expected, (int, float)) and not isinstance(expected, bool)
                raw = table[key][metric]
                parsed = _as_float(raw, str(slice_name), str(arm), metric)
                assert parsed == float(expected), (
                    f"{slice_name} {arm} {metric}: journal {raw!r} != json {expected!r}"
                )


def test_journal_states_postgres_was_not_seeded() -> None:
    report = _json(EVAL_PATH)
    volume = report["volume"]
    assert isinstance(volume, dict)
    assert volume["postgres"] is None
    assert volume["postgres_reason"] == POSTGRES_REASON
    section = _stage4_section(_read(JOURNAL_PATH))
    assert POSTGRES_REASON in section
    assert "volume.postgres" in section
    assert "null" in section


def test_journal_quotes_manifest_shares_as_fractions() -> None:
    manifest = _json(MANIFEST_PATH)
    shares = manifest["shares"]
    assert isinstance(shares, dict)
    section = _stage4_section(_read(JOURNAL_PATH))
    for key in SHARE_KEYS:
        assert key in shares, f"manifest.shares missing {key}"
        value = shares[key]
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        token = json.dumps(value)
        assert _number_token(section, token), (
            f"manifest share {key}={token} is missing from the journal as a fraction"
        )


def test_journal_records_holdout_gate() -> None:
    report = _json(EVAL_PATH)
    gate = report["holdout_gate"]
    assert isinstance(gate, dict)
    sha256 = gate["sha256"]
    rows = gate["rows"]
    assert isinstance(sha256, str) and sha256
    assert isinstance(rows, int) and not isinstance(rows, bool)
    section = _stage4_section(_read(JOURNAL_PATH))
    assert sha256 in section, "holdout_gate.sha256 is missing from the journal"
    assert re.search(rf"rows {rows}(?![0-9])", section), f"journal is missing rows {rows}"


def test_journal_records_marker_decision_without_noise_lever() -> None:
    report = _json(EVAL_PATH)
    assert report["decision_source"] == "markers"
    section = _stage4_section(_read(JOURNAL_PATH))
    assert "decision_source" in section
    assert "markers" in section
    assert "не наблюдался" in section


def test_journal_records_h2_as_not_done() -> None:
    report = _json(EVAL_PATH)
    h2 = report["h2"]
    assert isinstance(h2, dict)
    assert h2["implemented"] is False
    assert h2["needed"] is False
    assert h2["reason"] == H2_REASON
    section = _stage4_section(_read(JOURNAL_PATH))
    assert _field_is_false(section, "implemented"), "journal is missing implemented false"
    assert _field_is_false(section, "needed"), "journal is missing needed false"
    assert H2_REASON in section
    assert "Классификатор" in section
    assert "MLflow" in section
    assert "недельный cron" in section
    assert "несделанное" in section


def _single_heading_index(lines: list[str], heading: str) -> int:
    starts = [index for index, line in enumerate(lines) if line.strip() == heading]
    assert len(starts) == 1, f"expected one {heading!r}, found {len(starts)}"
    return starts[0]


def test_packaging_docs_omit_rejected_phrases() -> None:
    journal_lines = _read(JOURNAL_PATH).splitlines()
    journal_start, journal_end = _stage4_span(journal_lines)
    readme_lines = _read(README_PATH).splitlines()
    readme_start = _single_heading_index(readme_lines, README_SUMMARY_HEADING)
    checklist_lines = _read(CHECKLIST_PATH).splitlines()
    feedback_start = _single_heading_index(checklist_lines, CHECKLIST_FEEDBACK_HEADING)
    todos_start = _single_heading_index(checklist_lines, CHECKLIST_TODO_HEADING)
    assert feedback_start < todos_start
    slices = (
        (
            "journal 2026-10-25",
            "\n".join(journal_lines[journal_start:journal_end]),
            journal_start + 1,
        ),
        (
            "readme ### Замер саммари",
            "\n".join(readme_lines[readme_start:]),
            readme_start + 1,
        ),
        (
            "checklist feedback",
            "\n".join(checklist_lines[feedback_start:todos_start]),
            feedback_start + 1,
        ),
    )
    violations: list[str] = []
    for label, text, first_line in slices:
        violations.extend(_phrase_hits(label, text, REJECTED_PHRASES, first_line=first_line))
    assert not violations, "rejected phrase present:\n" + "\n".join(violations)


def test_readme_summary_command_matches_checklist() -> None:
    readme = _read(README_PATH)
    checklist = _read(CHECKLIST_PATH)
    assert README_SUMMARY_HEADING in readme
    readme_command = _eval_command(_markdown_section(readme, README_SUMMARY_HEADING))
    checklist_command = _eval_command(_markdown_section(checklist, CHECKLIST_FEEDBACK_HEADING))
    assert readme_command == checklist_command, (
        f"readme command {readme_command!r} != checklist command {checklist_command!r}"
    )
    assert EVAL_COMMAND in readme_command
    assert EVAL_MODEL_FLAG in readme_command
    assert EVAL_EMBEDDING_FLAG in readme_command


def test_checklist_feedback_section_precedes_open_todos_without_test_48() -> None:
    checklist = _read(CHECKLIST_PATH)
    feedback_at = checklist.find(CHECKLIST_FEEDBACK_HEADING)
    todos_at = checklist.find(CHECKLIST_TODO_HEADING)
    assert feedback_at != -1, f"checklist is missing {CHECKLIST_FEEDBACK_HEADING!r}"
    assert todos_at != -1, f"checklist is missing {CHECKLIST_TODO_HEADING!r}"
    assert feedback_at < todos_at, (
        f"{CHECKLIST_FEEDBACK_HEADING!r} does not precede {CHECKLIST_TODO_HEADING!r}"
    )
    section = _markdown_section(checklist, CHECKLIST_FEEDBACK_HEADING)
    assert "Test 48" not in section

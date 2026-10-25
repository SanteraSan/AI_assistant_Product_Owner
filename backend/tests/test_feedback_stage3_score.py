"""Stage 3 marker scores, holdout gate, H1 filter, and eval-script flags.

No HTTP server, no Ollama, and no live Qdrant. Holdout, manifest, and gold
are read-only. The eval script is not run with the models that would open
Qdrant or write research/feedback_summary_eval_latest.json.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from qdrant_client.http import models

from app.clients.qdrant_store import QdrantStore, _payload_filter
from app.services.feedback_eval_index import (
    EVAL_COLLECTION_NAME,
    EVAL_TENANT_ID,
    EVAL_TOP_K,
    arm_index_filter,
    assert_eval_collection_is_not_product,
    build_eval_point_payload,
    retrieve_arm,
)
from app.services.feedback_index_policy import FEEDBACK_CLASSES
from app.services.feedback_rules import SCENARIO_IDS, lexicon_rule_class
from app.services.feedback_summary_score import (
    GoldQuestion,
    JudgeScore,
    MarkerScore,
    RetrievedSource,
    accept_h1,
    assert_gold_matches_manifest,
    check_holdout_gate,
    h2_note,
    judge_diverged,
    load_summary_gold,
    parse_judge_payload,
    score_answer_coverage,
    score_faithfulness,
    score_markers,
    score_retrieval_recall,
)
from app.services.sql_schema_card import DEFAULT_SQL_TOOL_ALLOWED_TABLES, build_schema_card
import scripts.eval_feedback_summary as eval_feedback_summary

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_DIR = REPO_ROOT / "data" / "feedback" / "v1"
HOLDOUT_PATH = V1_DIR / "holdout.jsonl"
MANIFEST_PATH = V1_DIR / "manifest.json"
GOLD_PATH = V1_DIR / "summary_gold.json"
SCRIPT_PATH = REPO_ROOT / "backend" / "scripts" / "eval_feedback_summary.py"
USER_PROMPT_PATH = REPO_ROOT / "research" / "prompts" / "feedback_summary_user.txt"
JUDGE_PROMPT_PATH = REPO_ROOT / "research" / "prompts" / "feedback_summary_judge.txt"

FOREIGN_TENANT = "tenant-foreign-stage3"
FOREIGN_BUCKET = "bucket-foreign-stage3"
BUG_EXPECTED = ("notifications", "permissions", "search", "reports")
FEATURE_EXPECTED = ("webhooks", "integrations", "tasks", "projects")
KLASS_LINE = '{"text":"Класс!","generator_class":"bug","scenario_id":null}\n'
PHONE = "+7 901 555-66-77"
H2_K_CAP_REASON = "recall capped by k, not by repeated scenarios"
H2_REPEAT_REASON = "every H1 search repeats a scenario while a gold id is missing"
PRODUCT_DEFAULT_NOT_USED = "The product default model is not used."


def _manifest() -> dict[str, object]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _scenarios_indexed() -> dict[str, list[str]]:
    indexed = _manifest()["scenarios_indexed"]
    assert isinstance(indexed, dict)
    return {"bug": list(indexed["bug"]), "feature": list(indexed["feature"])}


def _question(
    question_id: str,
    slice_name: str,
    expected: tuple[str, ...] | list[str],
    must_not: tuple[str, ...] = ("Класс!",),
) -> GoldQuestion:
    return GoldQuestion(
        question_id=question_id,  # type: ignore[arg-type]
        slice=slice_name,  # type: ignore[arg-type]
        question="Собери саммари.",
        expected_scenario_ids=tuple(expected),
        must_not=must_not,
    )


def _source(
    corpus_id: str,
    scenario_id: str | None,
    content: str,
    *,
    index_in_rag: bool = True,
) -> RetrievedSource:
    return RetrievedSource(
        corpus_id=corpus_id,
        scenario_id=scenario_id,
        index_in_rag=index_in_rag,
        content=content,
    )


def _marker(
    *,
    retrieval_recall: float = 1.0,
    faithfulness: float = 1.0,
    answer_coverage: float = 1.0,
    must_not_hits: tuple[str, ...] = (),
) -> MarkerScore:
    return MarkerScore(
        retrieval_recall=retrieval_recall,
        faithfulness=faithfulness,
        answer_coverage=answer_coverage,
        support_ratio=faithfulness,
        retrieved_scenario_ids=(),
        answer_scenario_ids=(),
        supported_scenario_ids=(),
        unsupported_scenario_ids=(),
        covered_scenario_ids=(),
        must_not_hits=must_not_hits,
    )


def _judge(
    faithfulness: float,
    answer_coverage: float,
    *,
    must_not_present: bool = False,
) -> JudgeScore:
    return JudgeScore(
        faithfulness=faithfulness,
        answer_coverage=answer_coverage,
        must_not_present=must_not_present,
        scenario_ids=(),
    )


def _judge_json(**overrides: object) -> str:
    payload: dict[str, object] = {
        "faithfulness": 0.5,
        "answer_coverage": 0.5,
        "must_not_present": False,
        "scenario_ids": ["notifications"],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _conditions(query_filter: models.Filter | None) -> list[models.FieldCondition]:
    assert query_filter is not None
    must = query_filter.must or []
    return [item for item in must if isinstance(item, models.FieldCondition)]


def _condition(query_filter: models.Filter | None, key: str) -> models.FieldCondition:
    found = [item for item in _conditions(query_filter) if item.key == key]
    assert len(found) == 1, key
    return found[0]


def _match_value(query_filter: models.Filter | None, key: str) -> object:
    match = _condition(query_filter, key).match
    assert isinstance(match, models.MatchValue)
    return match.value


def _row(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "corpus_id": "fb-v1-9001",
        "rule_class": "noise",
        "index_in_rag": False,
        "index_text": "Класс!",
        "text": "Класс!",
        "scenario_id": None,
    }
    payload.update(overrides)
    return payload


class _RecordingStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search(
        self,
        query_vector: list[float],
        limit: int,
        tenant_id: str | None = None,
        bucket_ids: list[str] | None = None,
        index_in_rag: bool | None = None,
    ) -> list[object]:
        self.calls.append(
            {
                "query_vector": list(query_vector),
                "limit": limit,
                "tenant_id": tenant_id,
                "bucket_ids": list(bucket_ids or []),
                "index_in_rag": index_in_rag,
            }
        )
        return []


class _FakeQdrant:
    """Records filter arguments. Does not open a socket or store points."""

    def __init__(self) -> None:
        self.query_kwargs: dict[str, object] | None = None
        self.scroll_kwargs: dict[str, object] | None = None

    def query_points(self, **kwargs: object) -> SimpleNamespace:
        self.query_kwargs = kwargs
        return SimpleNamespace(points=[])

    def scroll(self, **kwargs: object) -> tuple[list[object], None]:
        self.scroll_kwargs = kwargs
        return [], None

    def upsert(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("stage 3 test must not upsert Qdrant points")


def _detached_store(client: _FakeQdrant) -> QdrantStore:
    store = QdrantStore.__new__(QdrantStore)
    store._client = client  # type: ignore[assignment]
    store._collection_name = EVAL_COLLECTION_NAME
    return store


def _output_fingerprint() -> tuple[int | None, bytes | None]:
    path = eval_feedback_summary._OUTPUT_PATH
    if not path.exists():
        return None, None
    return path.stat().st_mtime_ns, path.read_bytes()


def _forbid_live_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("flag check must return before Qdrant, Ollama, or protocol load")

    monkeypatch.setattr(eval_feedback_summary, "_prepare", _forbidden)
    monkeypatch.setattr(eval_feedback_summary, "_evaluate", _forbidden)
    monkeypatch.setattr(eval_feedback_summary, "QdrantStore", _forbidden)
    monkeypatch.setattr(eval_feedback_summary, "OllamaClient", _forbidden)


def test_retrieval_recall_counts_each_gold_id_once() -> None:
    """Two of four gold ids score 0.5. A repeat and scenario_id=None do not raise it."""

    base = [
        _source("c1", "notifications", "уведомления"),
        _source("c2", "permissions", "права"),
    ]
    assert score_retrieval_recall(expected=BUG_EXPECTED, sources=base) == 0.5

    with_repeat_and_empty = [
        *base,
        _source("c3", "notifications", "уведомления ещё раз"),
        _source("c4", None, "без сценария"),
    ]
    assert score_retrieval_recall(expected=BUG_EXPECTED, sources=with_repeat_and_empty) == 0.5

    with_third_gold_id = [*base, _source("c5", "search", "поиск")]
    assert score_retrieval_recall(expected=BUG_EXPECTED, sources=with_third_gold_id) == 0.75


def test_unsupported_answer_topic_lowers_support_ratio() -> None:
    """A scenario named in the answer but absent from sources lowers support_ratio."""

    sources = [_source("c1", "notifications", "уведомления не приходят")]
    full, full_ratio, full_hits = score_faithfulness(
        answer="notifications",
        sources=sources,
        must_not=("Класс!",),
        vocabulary=SCENARIO_IDS,
    )
    partial, partial_ratio, partial_hits = score_faithfulness(
        answer="notifications и search",
        sources=sources,
        must_not=("Класс!",),
        vocabulary=SCENARIO_IDS,
    )
    assert full_hits == ()
    assert partial_hits == ()
    assert full_ratio == 1.0
    assert full == 1.0
    assert partial_ratio == 0.5
    assert partial_ratio < full_ratio
    assert partial == 0.5


def test_klass_substring_zeroes_faithfulness_when_support_is_full() -> None:
    """The must-not substring «Класс!» forces faithfulness to 0 at full support."""

    faithfulness, support_ratio, hits = score_faithfulness(
        answer="Сбой в notifications. Класс!",
        sources=[_source("c1", "notifications", "уведомления")],
        must_not=("Класс!", "Супер!!!"),
        vocabulary=SCENARIO_IDS,
    )
    assert support_ratio == 1.0
    assert faithfulness == 0.0
    assert hits == ("Класс!",)


def test_empty_answer_without_must_not_hit_is_faithful_and_covers_nothing() -> None:
    """Silence does not hit must-not, so faithfulness is 1 and coverage is 0."""

    faithfulness, support_ratio, hits = score_faithfulness(
        answer="",
        sources=[_source("c1", "notifications", "уведомления")],
        must_not=("Класс!",),
        vocabulary=SCENARIO_IDS,
    )
    coverage = score_answer_coverage(
        answer="",
        expected=BUG_EXPECTED,
        vocabulary=SCENARIO_IDS,
    )
    assert hits == ()
    assert support_ratio == 1.0
    assert faithfulness == 1.0
    assert coverage == 0.0


def test_answer_coverage_ignores_ids_outside_expected_gold() -> None:
    """One named gold id of four is 0.25. An id outside that gold does not add to it."""

    only_gold = score_answer_coverage(
        answer="notifications",
        expected=BUG_EXPECTED,
        vocabulary=SCENARIO_IDS,
    )
    with_outside = score_answer_coverage(
        answer="notifications webhooks",
        expected=BUG_EXPECTED,
        vocabulary=SCENARIO_IDS,
    )
    scored = score_markers(
        gold=_question("critical_bugs", "bug", BUG_EXPECTED),
        answer="notifications webhooks",
        sources=[
            _source("c1", "notifications", "уведомления"),
            _source("c2", "webhooks", "вебхуки"),
        ],
        vocabulary=SCENARIO_IDS,
    )
    assert only_gold == 0.25
    assert with_outside == 0.25
    assert scored.answer_coverage == 0.25
    assert scored.covered_scenario_ids == ("notifications",)


def test_bug_and_feature_questions_do_not_share_numerators() -> None:
    """Different expected ids keep bug and feature recall and coverage apart."""

    sources = [
        _source("c1", "notifications", "уведомления"),
        _source("c2", "permissions", "права"),
        _source("c3", "notifications", "повтор"),
        _source("c4", None, "без сценария"),
        _source("c5", "webhooks", "вебхуки"),
    ]
    answer = "notifications permissions webhooks"
    bug = score_markers(
        gold=_question("critical_bugs", "bug", BUG_EXPECTED),
        answer=answer,
        sources=sources,
        vocabulary=SCENARIO_IDS,
    )
    feature = score_markers(
        gold=_question("requested_features", "feature", FEATURE_EXPECTED),
        answer=answer,
        sources=sources,
        vocabulary=SCENARIO_IDS,
    )
    assert bug.retrieval_recall == 0.5
    assert feature.retrieval_recall == 0.25
    assert bug.answer_coverage == 0.5
    assert feature.answer_coverage == 0.25
    assert bug.retrieval_recall != feature.retrieval_recall


def test_judge_diverges_when_gap_exceeds_limit_or_must_not_disagrees() -> None:
    """A gap of 0.06 on either marker, or a must-not disagreement, is divergence."""

    assert judge_diverged(markers=_marker(faithfulness=0.0, answer_coverage=1.0), judge=_judge(0.06, 1.0))
    assert judge_diverged(markers=_marker(faithfulness=1.0, answer_coverage=1.0), judge=_judge(0.94, 1.0))
    assert judge_diverged(markers=_marker(faithfulness=0.5, answer_coverage=0.0), judge=_judge(0.5, 0.06))
    assert judge_diverged(
        markers=_marker(faithfulness=0.5, answer_coverage=0.5, must_not_hits=("Класс!",)),
        judge=_judge(0.5, 0.5, must_not_present=False),
    )
    assert judge_diverged(
        markers=_marker(faithfulness=0.5, answer_coverage=0.5),
        judge=_judge(0.5, 0.5, must_not_present=True),
    )


def test_judge_gap_of_exactly_005_is_not_diverged() -> None:
    """A decimal gap of 0.05 stays inside the limit, including the 1.0 versus 0.95 float residue."""

    assert (
        judge_diverged(markers=_marker(faithfulness=0.0, answer_coverage=0.0), judge=_judge(0.05, 0.0))
        is False
    )
    assert (
        judge_diverged(markers=_marker(faithfulness=1.0, answer_coverage=1.0), judge=_judge(0.95, 0.95))
        is False
    )
    assert (
        judge_diverged(markers=_marker(faithfulness=0.5, answer_coverage=0.0), judge=_judge(0.5, 0.05))
        is False
    )


def test_parse_judge_payload_rejects_broken_text_and_out_of_range_numbers() -> None:
    """Broken text is None. Scores outside [0, 1] are None. The closed interval still parses."""

    assert parse_judge_payload("это не json") is None
    assert parse_judge_payload("{") is None
    assert parse_judge_payload(_judge_json(faithfulness=1.2)) is None
    assert parse_judge_payload(_judge_json(faithfulness=-0.01)) is None
    assert parse_judge_payload(_judge_json(answer_coverage=1.5)) is None
    assert parse_judge_payload(_judge_json(answer_coverage=-0.2)) is None

    parsed = parse_judge_payload("заметка " + _judge_json(faithfulness=0, answer_coverage=1))
    assert parsed is not None
    assert parsed.faithfulness == 0.0
    assert parsed.answer_coverage == 1.0
    assert parsed.must_not_present is False


def test_accept_h1_rejects_worse_recall_without_fixed_thresholds() -> None:
    """H1 recall below H0 is refused even though both scores sit under 0.65 and 0.85."""

    result = accept_h1(
        bugs_h0=[_marker(retrieval_recall=0.20, faithfulness=0.30)],
        bugs_h1=[_marker(retrieval_recall=0.10, faithfulness=0.30)],
    )
    assert result.retrieval_recall_not_regressed is False
    assert result.faithfulness_not_regressed is True
    assert result.bugs_must_not_cleared is True
    assert result.accepted is False


def test_accept_h1_rejects_when_must_not_remains_in_h1() -> None:
    """Equal marker means still refuse H1 when a must-not hit remains."""

    result = accept_h1(
        bugs_h0=[_marker(retrieval_recall=0.20, faithfulness=0.30)],
        bugs_h1=[_marker(retrieval_recall=0.20, faithfulness=0.30, must_not_hits=("Класс!",))],
    )
    assert result.bugs_must_not_cleared is False
    assert result.bugs_must_not_hit_runs_h1 == 1
    assert result.faithfulness_not_regressed is True
    assert result.retrieval_recall_not_regressed is True
    assert result.accepted is False


def test_accept_h1_accepts_bug_slice_below_fixed_thresholds() -> None:
    """Equal means under 0.65 and 0.85 are enough. Features are not an argument."""

    assert set(inspect.signature(accept_h1).parameters) == {"bugs_h0", "bugs_h1"}
    low = _marker(retrieval_recall=0.20, faithfulness=0.30)
    assert low.retrieval_recall < 0.65
    assert low.faithfulness < 0.85
    result = accept_h1(bugs_h0=[low], bugs_h1=[_marker(retrieval_recall=0.20, faithfulness=0.30)])
    assert result.bugs_must_not_cleared is True
    assert result.faithfulness_not_regressed is True
    assert result.retrieval_recall_not_regressed is True
    assert result.accepted is True


def test_h2_note_five_distinct_ids_are_the_k_ceiling() -> None:
    """Five distinct ids at k=5 leave gold uncovered, but that is the k ceiling."""

    gold = _scenarios_indexed()["bug"]
    assert len(gold) > 5
    five = [
        _source(f"c{index}", scenario_id, scenario_id)
        for index, scenario_id in enumerate(gold[:5])
    ]
    note = h2_note(bugs_h1_sources=[five, five], expected_scenario_ids=gold, top_k=5)
    assert note["implemented"] is False
    assert note["needed"] is False
    assert note["reason"] == H2_K_CAP_REASON
    assert note["capacity"] == 5
    assert note["mean_unique_scenarios"] == 5.0
    assert note["never_found"]


def test_h2_note_repeated_id_with_missing_gold_is_needed() -> None:
    """Every top-k repeating one id, while other gold ids are missing, needs H2."""

    gold = _scenarios_indexed()["bug"]
    repeated = [_source(f"c{index}", "notifications", "уведомления") for index in range(5)]
    note = h2_note(
        bugs_h1_sources=[repeated, list(repeated)],
        expected_scenario_ids=gold,
        top_k=5,
    )
    assert note["implemented"] is False
    assert note["needed"] is True
    assert note["reason"] == H2_REPEAT_REASON
    assert note["mean_unique_scenarios"] == 1.0
    assert "permissions" in note["never_found"]


def test_frozen_holdout_matches_manifest_sha_and_has_20_rows() -> None:
    """The frozen holdout bytes match the manifest hash and contain 20 rows."""

    manifest = _manifest()
    assert manifest["holdout_rows"] == 20
    expected_sha = manifest["holdout_sha256"]
    assert isinstance(expected_sha, str) and len(expected_sha) == 64
    raw = HOLDOUT_PATH.read_bytes()
    result = check_holdout_gate(holdout_bytes=raw, expected_sha256=expected_sha, expected_rows=20)
    assert result.ok is True
    assert result.rows == 20
    assert result.sha256 == expected_sha
    assert result.mismatches == ()


def test_holdout_gate_rejects_19_rows_or_a_different_sha() -> None:
    """Nineteen rows or a different hash fail the gate."""

    raw = HOLDOUT_PATH.read_bytes()
    expected_sha = str(_manifest()["holdout_sha256"])
    lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
    assert len(lines) == 20
    short = check_holdout_gate(
        holdout_bytes=("\n".join(lines[:19]) + "\n").encode("utf-8"),
        expected_sha256=expected_sha,
        expected_rows=20,
    )
    assert short.ok is False
    assert short.rows == 19

    wrong_sha = check_holdout_gate(
        holdout_bytes=raw,
        expected_sha256="0" * 64,
        expected_rows=20,
    )
    assert wrong_sha.ok is False
    assert wrong_sha.rows == 20
    assert wrong_sha.sha256 == expected_sha
    assert wrong_sha.sha256 != "0" * 64
    assert wrong_sha.mismatches == ()


def test_holdout_line_klass_labeled_bug_mismatches_as_noise() -> None:
    """A bug label on «Класс!» mismatches, and the lexicon class is noise."""

    raw = KLASS_LINE.encode("utf-8")
    result = check_holdout_gate(
        holdout_bytes=raw,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_rows=1,
    )
    assert result.rows == 1
    assert result.ok is False
    assert len(result.mismatches) == 1
    mismatch = result.mismatches[0]
    assert mismatch.line_no == 1
    assert mismatch.manual_class == "bug"
    assert mismatch.rule_class == "noise"
    assert mismatch.text_preview == "Класс!"


def test_holdout_gate_does_not_rewrite_holdout_file() -> None:
    """The gate hashes bytes it is given and leaves holdout.jsonl unchanged."""

    before_bytes = HOLDOUT_PATH.read_bytes()
    before_mtime = HOLDOUT_PATH.stat().st_mtime_ns
    expected_sha = str(_manifest()["holdout_sha256"])
    check_holdout_gate(holdout_bytes=before_bytes, expected_sha256=expected_sha, expected_rows=20)
    check_holdout_gate(holdout_bytes=KLASS_LINE.encode("utf-8"), expected_sha256=expected_sha)
    assert HOLDOUT_PATH.read_bytes() == before_bytes
    assert HOLDOUT_PATH.stat().st_mtime_ns == before_mtime


def test_lexicon_rule_class_handles_empty_and_long_text() -> None:
    """Empty text and a long text return a class instead of raising."""

    empty_class, empty_reason = lexicon_rule_class("", fallback_class="bug")
    long_text = "stage3-long-text-" + ("я" * 5000)
    assert len(long_text) > 1200
    long_class, long_reason = lexicon_rule_class(long_text, fallback_class="feature")
    assert empty_class in FEEDBACK_CLASSES
    assert long_class in FEEDBACK_CLASSES
    assert isinstance(empty_reason, str) and empty_reason
    assert isinstance(long_reason, str) and long_reason


def test_lexicon_rule_class_rejects_fallback_outside_four_classes() -> None:
    """A fallback outside noise, churn, bug, and feature raises ValueError."""

    with pytest.raises(ValueError, match="four feedback classes"):
        lexicon_rule_class("Класс!", fallback_class="praise")


def test_payload_filter_omits_index_in_rag_when_unset() -> None:
    """index_in_rag=None leaves the key out of the filter."""

    query_filter = _payload_filter(
        FOREIGN_TENANT,
        [FOREIGN_BUCKET],
        [],
        [],
        [],
        [],
        index_in_rag=None,
    )
    assert all(item.key != "index_in_rag" for item in _conditions(query_filter))
    assert _match_value(query_filter, "tenant_id") == FOREIGN_TENANT


def test_payload_filter_matches_index_in_rag_true_and_false() -> None:
    """True and False each become a MatchValue of that boolean."""

    enabled = _payload_filter("tenant-a", ["bucket-a"], [], [], [], [], index_in_rag=True)
    disabled = _payload_filter("tenant-a", ["bucket-a"], [], [], [], [], index_in_rag=False)
    enabled_match = _condition(enabled, "index_in_rag").match
    disabled_match = _condition(disabled, "index_in_rag").match
    assert isinstance(enabled_match, models.MatchValue)
    assert isinstance(disabled_match, models.MatchValue)
    assert enabled_match.value is True
    assert disabled_match.value is False


def test_arm_index_filter_h0_is_none_h1_is_true_and_other_raises() -> None:
    """H0 does not filter the flag, H1 keeps true, and any other arm is refused."""

    assert arm_index_filter("H0") is None
    assert arm_index_filter("H1") is True
    with pytest.raises(ValueError):
        arm_index_filter("H2")  # type: ignore[arg-type]


def test_eval_payload_copies_noise_bug_and_duplicate_flags() -> None:
    """Noise and a duplicate stay out of the index. A flagged bug stays in."""

    noise = build_eval_point_payload(_row(corpus_id="fb-v1-0001", rule_class="noise", index_in_rag=False))
    bug = build_eval_point_payload(
        _row(
            corpus_id="fb-v1-0400",
            rule_class="bug",
            index_in_rag=True,
            scenario_id="permissions",
            index_text="Сохранение прав падает с 500",
        )
    )
    duplicate = build_eval_point_payload(
        _row(
            corpus_id="fb-v1-0501",
            rule_class="bug",
            index_in_rag=False,
            scenario_id="permissions",
            duplicate_of="fb-v1-0426",
            index_text="Сохранение прав падает с 500",
        )
    )
    assert noise["index_in_rag"] is False
    assert noise["feedback_class"] == "noise"
    assert bug["index_in_rag"] is True
    assert bug["feedback_class"] == "bug"
    assert duplicate["index_in_rag"] is False
    assert duplicate["feedback_class"] == "bug"


def test_eval_payload_content_comes_from_index_text_not_raw_text() -> None:
    """A phone that exists only in raw text is not stored. content is index_text."""

    index_text = "Сохранение прав падает с 500 на доске"
    raw_text = f"{index_text}. Телефон {PHONE}"
    assert PHONE not in index_text
    assert PHONE in raw_text
    payload = build_eval_point_payload(
        _row(
            corpus_id="fb-v1-0404",
            rule_class="bug",
            index_in_rag=True,
            scenario_id="permissions",
            index_text=index_text,
            text=raw_text,
        )
    )
    assert payload["content"] == index_text
    assert payload["embedded_placeholder"] is False
    assert "text" not in payload
    assert PHONE not in json.dumps(payload, ensure_ascii=False)


def test_eval_payload_empty_index_text_is_a_placeholder() -> None:
    """An empty index_text is embedded as '.' and marked as a placeholder."""

    payload = build_eval_point_payload(
        _row(corpus_id="fb-v1-0002", index_text="", text="сырой текст не становится content")
    )
    assert payload["content"] == "."
    assert payload["embedded_placeholder"] is True
    assert "сырой текст" not in payload["content"]


def test_eval_collection_name_must_not_be_the_product_collection() -> None:
    """Empty, documents, and the product name are refused. feedback_eval_v1 is allowed."""

    with pytest.raises(ValueError):
        assert_eval_collection_is_not_product(collection_name="", product_collection="documents")
    with pytest.raises(ValueError):
        assert_eval_collection_is_not_product(collection_name="   ", product_collection="documents")
    with pytest.raises(ValueError):
        assert_eval_collection_is_not_product(collection_name="documents", product_collection="qdrant_docs")
    with pytest.raises(ValueError):
        assert_eval_collection_is_not_product(
            collection_name="qdrant_docs",
            product_collection="qdrant_docs",
        )
    assert EVAL_COLLECTION_NAME == "feedback_eval_v1"
    assert (
        assert_eval_collection_is_not_product(
            collection_name=EVAL_COLLECTION_NAME,
            product_collection="documents",
        )
        is None
    )


def test_gold_matches_manifest_copy_and_rejects_extra_or_empty_ids() -> None:
    """A copy of scenarios_indexed matches. An extra id or an empty list does not."""

    indexed = _scenarios_indexed()
    questions = (
        _question("critical_bugs", "bug", indexed["bug"], must_not=()),
        _question("requested_features", "feature", indexed["feature"], must_not=()),
    )
    assert_gold_matches_manifest(questions, {"scenarios_indexed": indexed})
    assert_gold_matches_manifest(load_summary_gold(GOLD_PATH), {"scenarios_indexed": _scenarios_indexed()})

    extra = indexed["bug"] + ["extra_scenario"]
    with pytest.raises(ValueError):
        assert_gold_matches_manifest(
            (_question("critical_bugs", "bug", extra), questions[1]),
            {"scenarios_indexed": _scenarios_indexed()},
        )
    with pytest.raises(ValueError):
        assert_gold_matches_manifest(
            (_question("critical_bugs", "bug", []), questions[1]),
            {"scenarios_indexed": _scenarios_indexed()},
        )


def test_foreign_tenant_is_the_tenant_in_search_and_scroll_filters() -> None:
    """retrieve_arm, search, and scroll keep the caller tenant instead of the eval default."""

    assert FOREIGN_TENANT != EVAL_TENANT_ID
    recorder = _RecordingStore()
    retrieve_arm(
        recorder,  # type: ignore[arg-type]
        arm="H1",
        query_vector=[0.2],
        tenant_id=FOREIGN_TENANT,
        bucket_id=FOREIGN_BUCKET,
        top_k=EVAL_TOP_K,
    )
    retrieve_arm(
        recorder,  # type: ignore[arg-type]
        arm="H0",
        query_vector=[0.2],
        tenant_id=FOREIGN_TENANT,
        bucket_id=FOREIGN_BUCKET,
        top_k=EVAL_TOP_K,
    )
    assert recorder.calls[0]["tenant_id"] == FOREIGN_TENANT
    assert recorder.calls[0]["bucket_ids"] == [FOREIGN_BUCKET]
    assert recorder.calls[0]["index_in_rag"] is True
    assert recorder.calls[0]["limit"] == EVAL_TOP_K
    assert recorder.calls[1]["tenant_id"] == FOREIGN_TENANT
    assert recorder.calls[1]["index_in_rag"] is None

    client = _FakeQdrant()
    store = _detached_store(client)
    h1_call = recorder.calls[0]
    store.search(
        h1_call["query_vector"],  # type: ignore[arg-type]
        h1_call["limit"],  # type: ignore[arg-type]
        h1_call["tenant_id"],  # type: ignore[arg-type]
        h1_call["bucket_ids"],  # type: ignore[arg-type]
        index_in_rag=h1_call["index_in_rag"],  # type: ignore[arg-type]
    )
    assert client.query_kwargs is not None
    query_filter = client.query_kwargs["query_filter"]
    assert isinstance(query_filter, models.Filter)
    assert _match_value(query_filter, "tenant_id") == FOREIGN_TENANT
    assert _match_value(query_filter, "tenant_id") != EVAL_TENANT_ID
    bucket_match = _condition(query_filter, "bucket_id").match
    assert isinstance(bucket_match, models.MatchAny)
    assert list(bucket_match.any) == [FOREIGN_BUCKET]
    assert _match_value(query_filter, "index_in_rag") is True

    store.scroll(
        limit=EVAL_TOP_K,
        tenant_id=FOREIGN_TENANT,
        bucket_ids=[FOREIGN_BUCKET],
        index_in_rag=False,
    )
    assert client.scroll_kwargs is not None
    scroll_filter = client.scroll_kwargs["scroll_filter"]
    assert isinstance(scroll_filter, models.Filter)
    assert _match_value(scroll_filter, "tenant_id") == FOREIGN_TENANT
    assert _match_value(scroll_filter, "index_in_rag") is False

    direct = _payload_filter(FOREIGN_TENANT, [FOREIGN_BUCKET], [], [], [], [], index_in_rag=None)
    assert _match_value(direct, "tenant_id") == FOREIGN_TENANT
    assert _match_value(direct, "tenant_id") != EVAL_TENANT_ID


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="missing-args"),
        pytest.param(["--embedding-model", "nomic-embed-text"], id="missing-model"),
        pytest.param(
            ["--model", "qwen3.5:9b", "--embedding-model", "nomic-embed-text"],
            id="wrong-model",
        ),
    ],
)
def test_main_rejects_missing_or_wrong_chat_model(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing or non-qwen3.8:latest model exits 2 before Qdrant and does not write the report."""

    before = _output_fingerprint()
    _forbid_live_eval(monkeypatch)
    if argv == []:
        with pytest.raises(SystemExit) as caught:
            eval_feedback_summary.parse_args([])
        assert caught.value.code == 2
    code = eval_feedback_summary.main(argv)
    assert code == 2
    assert PRODUCT_DEFAULT_NOT_USED in capsys.readouterr().err
    assert _output_fingerprint() == before


def test_main_rejects_wrong_embedding_model(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An embedding model other than nomic-embed-text exits 2 and does not write the report."""

    before = _output_fingerprint()
    _forbid_live_eval(monkeypatch)
    code = eval_feedback_summary.main(
        ["--model", "qwen3.8:latest", "--embedding-model", "bge-m3"]
    )
    assert code == 2
    assert PRODUCT_DEFAULT_NOT_USED in capsys.readouterr().err
    assert _output_fingerprint() == before


def test_main_help_exits_0(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--help exits 0 and does not write the report."""

    before = _output_fingerprint()
    _forbid_live_eval(monkeypatch)
    code = eval_feedback_summary.main(["--help"])
    captured = capsys.readouterr()
    assert code == 0
    assert "--model" in captured.out
    assert _output_fingerprint() == before


def test_eval_script_does_not_read_product_model_settings() -> None:
    """The run model comes from flags. Product model settings are not read."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "settings":
            used.add(node.attr)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "get_settings":
                used.add(node.attr)
    forbidden = {"default_model", "default_rag_model", "agent_default_model", "embedding_model"}
    assert used.isdisjoint(forbidden)
    for name in forbidden:
        assert f"settings.{name}" not in source
        assert f"get_settings().{name}" not in source


def test_eval_script_does_not_import_seed_db_kafka_or_readonly_sql() -> None:
    """The measurement script does not import seeding, database init, Kafka, or readonly SQL."""

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
            imported.update(alias.name for alias in node.names)
    assert "seed_feedback_items" not in imported
    assert "init_db" not in imported
    assert "execute_readonly_sql" not in imported
    assert not any("kafka" in name.lower() for name in imported)
    lowered = source.lower()
    assert "seed_feedback_items" not in source
    assert "init_db" not in source
    assert "execute_readonly_sql" not in source
    assert "kafka" not in lowered


def test_eval_script_and_prompts_do_not_log_api_key_or_authorization() -> None:
    """The script and prompts do not contain api_key or Authorization, so they cannot log them."""

    script = SCRIPT_PATH.read_text(encoding="utf-8")
    user_prompt = USER_PROMPT_PATH.read_text(encoding="utf-8")
    judge_prompt = JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    for label, text in (
        ("script", script),
        ("user prompt", user_prompt),
        ("judge prompt", judge_prompt),
    ):
        assert "api_key" not in text, label
        assert "Authorization" not in text, label
    assert "import logging" not in script
    assert "logger." not in script


def test_feedback_items_stay_out_of_readonly_sql() -> None:
    """The feedback table is not part of execute_readonly_sql's allowlist."""

    assert "feedback_items" not in DEFAULT_SQL_TOOL_ALLOWED_TABLES
    assert "feedback_items" not in build_schema_card(allowed_tables=DEFAULT_SQL_TOOL_ALLOWED_TABLES)

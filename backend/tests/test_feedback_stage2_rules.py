"""Stage 2 feedback rules, corpus assembly, and sqlite seed.

JSONL is written only under pytest's temporary directory. The real holdout
and the rest of data/feedback/v1 are read-only. Seed runs through the
product _seed function against an in-memory SQLite engine; Postgres, Ollama,
Qdrant, MinIO, and Redpanda are not started.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.schema import CheckConstraint

from app.db.base import Base
from app.db.models import DocumentAsset, FeedbackItem, KnowledgeBucket
from app.services.document_indexing_service import FeedbackIndexRow, _feedback_chunks
from app.services.feedback_rules import (
    INDEX_TEXT_MAX_CHARS,
    SCENARIO_IDS,
    FeedbackCleanedRow,
    FeedbackSourceRow,
    _closed_lexicons,
    _refuse_holdout_write,
    apply_feedback_rules,
    assemble_raw_rows,
    build_manifest,
    build_rule_report,
    feedback_chunk_content,
    mask_pii,
    normalize_lexicon_key,
    write_corpus_files,
)
from app.services.sql_schema_card import DEFAULT_SQL_TOOL_ALLOWED_TABLES, build_schema_card
from scripts.build_feedback_corpus import _seed, main

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
APP_ROOT = BACKEND_ROOT / "app"
V1_DIR = REPO_ROOT / "data" / "feedback" / "v1"
HOLDOUT_PATH = V1_DIR / "holdout.jsonl"
MIGRATION_0010 = BACKEND_ROOT / "alembic" / "versions" / "20261023_0010_feedback_items_and_job_acl.py"
EXPECTED_HOLDOUT_SHA256 = "c4daa546033646b738e2709f0ae7a49c025e17f212ff4479b70382d81cb83728"

INPUTS = {
    "noise": Path("/home/santera/ML|LLM|RAG/sintetic_data/noise.jsonl"),
    "churn": Path("/home/santera/ML|LLM|RAG/sintetic_data/churn.jsonl"),
    "bugs": Path("/home/santera/ML|LLM|RAG/sintetic_data/bugs.jsonl"),
    "features": Path("/home/santera/ML|LLM|RAG/sintetic_data/features.jsonl"),
}
EXPECTED_INPUT_ROWS = {"noise": 350, "churn": 75, "bugs": 60, "features": 15}
COPY_PAIRS = [
    (f"fb-v1-{501 + offset:04d}", f"fb-v1-{426 + offset:04d}")
    for offset in range(8)
] + [
    ("fb-v1-0509", "fb-v1-0486"),
    ("fb-v1-0510", "fb-v1-0487"),
]
FEATURE_PER_SCENARIO = {
    "notifications": 2,
    "csv_import": 2,
    "permissions": 2,
    "reports": 2,
    "search": 2,
    "webhooks": 1,
    "integrations": 1,
    "tasks": 1,
    "projects": 1,
    "sprints": 1,
}
PHONE_RE = re.compile(r"\+7\s*\d{3}\s*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
CARD_RE = re.compile(r"\b\d{4}(?:\s+\d{4}){3}\b")
CLASS_CHECK = "feedback_class IN ('noise', 'churn_signal', 'bug', 'feature')"
INDEX_CHECK = "index_in_rag = false OR feedback_class IN ('bug', 'feature')"

TENANT_ID = "tenant-stage2"
OTHER_TENANT_ID = "tenant-other"
BUCKET_ID = "bucket-stage2"
OTHER_BUCKET_ID = "bucket-other"
FOREIGN_BUCKET_ID = "bucket-foreign"


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(type_, compiler, **kw):  # noqa: ANN001
    del type_, compiler, kw
    return "JSON"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl_texts(path: Path) -> list[str]:
    texts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        texts.append(payload["text"])
    return texts


def _nonempty_lines(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _assemble_from(paths: Mapping[str, Path]) -> list[FeedbackSourceRow]:
    return assemble_raw_rows(
        noise_path=paths["noise"],
        churn_path=paths["churn"],
        bugs_path=paths["bugs"],
        features_path=paths["features"],
    )


def _source(
    text: str,
    generator_class: str,
    *,
    corpus_id: str = "fb-v1-9000",
    scenario_id: str | None = None,
    line_no: int = 1,
) -> FeedbackSourceRow:
    if scenario_id is None and generator_class in {"bug", "feature"}:
        scenario_id = "permissions"
    return FeedbackSourceRow(
        corpus_id=corpus_id,
        generator_class=generator_class,
        scenario_id=scenario_id,
        text=text,
        source_file="fixture.jsonl",
        source_line=line_no,
        is_exact_duplicate=False,
        duplicate_of=None,
    )


def _cleaned_from(source: FeedbackSourceRow, **overrides: object) -> FeedbackCleanedRow:
    payload: dict[str, object] = {
        "source": source,
        "rule_class": source.generator_class,
        "index_in_rag": False,
        "rule_reason": "keep_generator",
        "index_text": source.text,
        "index_text_truncated": False,
    }
    payload.update(overrides)
    return FeedbackCleanedRow(**payload)  # type: ignore[arg-type]


def _bug_line(cleaned: list[FeedbackCleanedRow], line_no: int) -> FeedbackCleanedRow:
    matches = [
        row
        for row in cleaned
        if row.source.source_file == "bugs.jsonl"
        and row.source.source_line == line_no
        and not row.source.is_exact_duplicate
    ]
    assert len(matches) == 1
    return matches[0]


def _tiny_holdout(directory: Path) -> Path:
    path = directory / "tiny-holdout.jsonl"
    path.write_text('{"text":"holdout-not-used"}\n', encoding="utf-8")
    return path


def _copy_inputs(directory: Path, *, noise_suffix: str = "") -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, source in INPUTS.items():
        target = directory / source.name
        if name == "noise" and noise_suffix:
            lines = source.read_text(encoding="utf-8").splitlines()
            payload = json.loads(lines[0])
            payload["text"] = f"{payload['text']}{noise_suffix}"
            lines[0] = json.dumps(payload, ensure_ascii=False)
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            target.write_bytes(source.read_bytes())
        paths[name] = target
    return paths


def _source_sha(manifest: dict[str, object], filename: str) -> str:
    matches = [item for item in manifest["sources"] if str(item["path"]).endswith(filename)]  # type: ignore[index]
    assert len(matches) == 1
    return str(matches[0]["sha256"])


def _memory_engine():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    assert engine.dialect.name == "sqlite"
    Base.metadata.create_all(
        engine,
        tables=[
            KnowledgeBucket.__table__,
            DocumentAsset.__table__,
            FeedbackItem.__table__,
        ],
    )
    return engine


def _add_bucket(session: Session, *, bucket_id: str, tenant_id: str, name: str) -> None:
    session.add(
        KnowledgeBucket(
            id=bucket_id,
            tenant_id=tenant_id,
            name=name,
            description="",
            status="ready",
            metadata_json={},
        )
    )


def _feedback_snapshot(engine) -> tuple[tuple[object, ...], ...]:
    with Session(engine) as session:
        rows = session.scalars(select(FeedbackItem).order_by(FeedbackItem.id)).all()
        return tuple(
            (
                row.id,
                row.tenant_id,
                row.bucket_id,
                row.corpus_id,
                row.body,
                row.document_id,
                row.index_in_rag,
                row.feedback_class,
            )
            for row in rows
        )


class _ConnectionAdapter:
    def __init__(self, connection) -> None:  # noqa: ANN001
        self._connection = connection

    async def __aenter__(self) -> _ConnectionAdapter:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        self._connection.close()
        return False

    async def execute(self, statement):  # noqa: ANN001
        return self._connection.execute(statement)

    async def rollback(self) -> None:
        self._connection.rollback()


class _EngineAdapter:
    def __init__(self, engine) -> None:  # noqa: ANN001
        self._engine = engine

    def connect(self) -> _ConnectionAdapter:
        return _ConnectionAdapter(self._engine.connect())

    async def dispose(self) -> None:
        return None


class _BeginAdapter:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def __aenter__(self) -> _BeginAdapter:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        if exc_type is None:
            self._session.commit()
        else:
            self._session.rollback()
        return False


class _SessionAdapter:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def __aenter__(self) -> _SessionAdapter:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        self._session.close()
        return False

    def begin(self) -> _BeginAdapter:
        return _BeginAdapter(self._session)

    async def execute(self, statement):  # noqa: ANN001
        return self._session.execute(statement)

    def add_all(self, items) -> None:  # noqa: ANN001
        self._session.add_all(items)


def _install_sqlite_seed(monkeypatch: pytest.MonkeyPatch, engine) -> list[str]:  # noqa: ANN001
    opened: list[str] = []

    def fake_create_engine(dsn: str):
        opened.append(dsn)
        return _EngineAdapter(engine)

    def fake_session_factory(_engine):  # noqa: ANN001
        def factory() -> _SessionAdapter:
            return _SessionAdapter(Session(engine, expire_on_commit=False))

        return factory

    def forbidden_async_engine(*args, **kwargs):  # noqa: ANN001
        raise AssertionError(f"create_async_engine was called: {args[:1]}")

    monkeypatch.setattr("app.db.session.create_engine", fake_create_engine)
    monkeypatch.setattr("app.db.session.create_session_factory", fake_session_factory)
    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", forbidden_async_engine)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(
            postgres_dsn="postgresql+asyncpg://po_user:po_password@127.0.0.1:1/not_dialed",
            default_tenant_id="local_demo",
            default_bucket_id="taskflow_seed",
        ),
    )
    return opened


def _forbid_database(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    opened: list[object] = []

    def boom(*args, **kwargs):  # noqa: ANN001
        opened.append(args[:1])
        raise AssertionError(f"database engine opened: {args[:1]}")

    monkeypatch.setattr("app.db.session.create_engine", boom)
    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", boom)
    return opened


@pytest.fixture(autouse=True)
def _keep_real_feedback_corpus(monkeypatch: pytest.MonkeyPatch):
    real_dir = V1_DIR.resolve()
    real_holdout = HOLDOUT_PATH.resolve()
    before = {path.name: path.read_bytes() for path in real_dir.iterdir() if path.is_file()}
    assert hashlib.sha256(before["holdout.jsonl"]).hexdigest() == EXPECTED_HOLDOUT_SHA256
    original_text = Path.write_text
    original_bytes = Path.write_bytes

    def _blocked(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        if resolved == real_holdout or resolved.parent == real_dir:
            raise AssertionError(f"test blocked a write to {resolved}")

    def write_text(self: Path, *args, **kwargs):  # noqa: ANN001
        _blocked(self)
        return original_text(self, *args, **kwargs)

    def write_bytes(self: Path, *args, **kwargs):  # noqa: ANN001
        _blocked(self)
        return original_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text)
    monkeypatch.setattr(Path, "write_bytes", write_bytes)
    yield
    after = {path.name: path.read_bytes() for path in real_dir.iterdir() if path.is_file()}
    assert after == before


@pytest.fixture(scope="module")
def assembled_corpus() -> tuple[list[FeedbackSourceRow], list[FeedbackCleanedRow]]:
    raw_rows = _assemble_from(INPUTS)
    cleaned_rows = apply_feedback_rules(raw_rows)
    return raw_rows, cleaned_rows


def test_assembled_counts_shares_and_exact_input_lengths(assembled_corpus, tmp_path: Path) -> None:
    """Assertion 1: 510 rows, class shares, and exact input lengths."""
    raw_rows, cleaned_rows = assembled_corpus
    for name, expected in EXPECTED_INPUT_ROWS.items():
        assert _nonempty_lines(INPUTS[name]) == expected

    before = Counter(row.generator_class for row in raw_rows if not row.is_exact_duplicate)
    assert before == Counter({"noise": 350, "churn_signal": 75, "bug": 60, "feature": 15})
    assert len(raw_rows) == 510
    assert len(cleaned_rows) == 510

    counts = Counter(row.rule_class for row in cleaned_rows)
    assert counts == Counter({"noise": 350, "churn_signal": 75, "bug": 68, "feature": 17})
    targets = {"noise": 70.0, "churn_signal": 15.0, "bug": 12.0, "feature": 3.0}
    for name, target in targets.items():
        assert abs(counts[name] / 510 * 100 - target) <= 2.0

    manifest = build_manifest(cleaned_rows, holdout_path=_tiny_holdout(tmp_path))
    assert manifest["counts"] == {**{name: counts[name] for name in counts}, "total": 510}
    assert manifest["counts_before_duplicates"] == {
        "noise": 350,
        "churn_signal": 75,
        "bug": 60,
        "feature": 15,
        "total": 500,
    }
    assert manifest["shares_within_tolerance"] is True


@pytest.mark.parametrize("short_name", ["noise", "churn", "bugs", "features"])
def test_assembly_rejects_input_file_with_wrong_length(tmp_path: Path, short_name: str) -> None:
    """Assertion 1: assembly fails unless each input has its exact length."""
    paths = dict(INPUTS)
    source = INPUTS[short_name]
    lines = [line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    target = tmp_path / source.name
    target.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    paths[short_name] = target
    expected = EXPECTED_INPUT_ROWS[short_name]
    with pytest.raises(ValueError, match=rf"{source.name} has \d+ rows, expected {expected}"):
        _assemble_from(paths)


def test_corpus_ids_are_contiguous_and_copies_match_origins(assembled_corpus) -> None:
    """Assertion 2: fb-v1-0001..0510 and the ten exact copies at the end."""
    raw_rows, _cleaned_rows = assembled_corpus
    assert [row.corpus_id for row in raw_rows] == [f"fb-v1-{index:04d}" for index in range(1, 511)]
    by_id = {row.corpus_id: row for row in raw_rows}
    assert len(COPY_PAIRS) == 10
    for copy_id, origin_id in COPY_PAIRS[:8]:
        assert by_id[origin_id].generator_class == "bug"
    for copy_id, origin_id in COPY_PAIRS[8:]:
        assert by_id[origin_id].generator_class == "feature"
    for copy_id, origin_id in COPY_PAIRS:
        copy = by_id[copy_id]
        origin = by_id[origin_id]
        assert copy.duplicate_of == origin_id
        assert copy.text == origin.text
        assert by_id[copy.duplicate_of].text == copy.text
        assert copy.generator_class == origin.generator_class
        assert copy.scenario_id == origin.scenario_id
        assert copy.is_exact_duplicate is True


def test_scenario_ids_cover_the_ten_scenarios(assembled_corpus) -> None:
    """Assertion 3: bug/feature scenarios, including copies, and empty noise/churn."""
    raw_rows, _cleaned_rows = assembled_corpus
    assert len(SCENARIO_IDS) == 10
    for row in raw_rows:
        if row.generator_class in {"bug", "feature"}:
            assert row.scenario_id in SCENARIO_IDS
        else:
            assert row.generator_class in {"noise", "churn_signal"}
            assert row.scenario_id is None

    bugs = [row for row in raw_rows if row.generator_class == "bug" and not row.is_exact_duplicate]
    features = [row for row in raw_rows if row.generator_class == "feature" and not row.is_exact_duplicate]
    assert Counter(row.scenario_id for row in bugs) == {scenario: 6 for scenario in SCENARIO_IDS}
    assert Counter(row.scenario_id for row in features) == FEATURE_PER_SCENARIO
    assert set(FEATURE_PER_SCENARIO) == set(SCENARIO_IDS)


def test_lexicon_matches_whole_phrases_not_substrings() -> None:
    """Assertion 4: noise and churn phrases match the closed lexicons as whole strings."""
    noise_lexicon, churn_lexicon = _closed_lexicons()
    for text in _jsonl_texts(INPUTS["noise"]):
        assert normalize_lexicon_key(text) in noise_lexicon
    for text in _jsonl_texts(INPUTS["churn"]):
        assert normalize_lexicon_key(text) in churn_lexicon
    for path in (INPUTS["bugs"], INPUTS["features"]):
        for text in _jsonl_texts(path):
            key = normalize_lexicon_key(text)
            assert key not in noise_lexicon
            assert key not in churn_lexicon

    longer = "Клиент пишет Класс! но кнопка сохранения прав падает с 500 на доске"
    assert "Класс!" in longer
    assert normalize_lexicon_key(longer) not in noise_lexicon
    assert normalize_lexicon_key(longer) not in churn_lexicon
    classified = apply_feedback_rules([_source(longer, "bug")])[0]
    assert classified.rule_class == "bug"
    assert classified.index_in_rag is True

    churn_inside = "Удаляю не из-за шума, а потому что импорт CSV теряет строки задач"
    assert "Удаляю" in churn_inside
    assert normalize_lexicon_key(churn_inside) not in churn_lexicon
    still_bug = apply_feedback_rules([_source(churn_inside, "bug", corpus_id="fb-v1-9002")])[0]
    assert still_bug.rule_class == "bug"


def test_blank_text_is_noise_and_not_indexed() -> None:
    """Assertion 5: empty text and a single space become noise and stay out of the index."""
    for text in ("", " "):
        row = apply_feedback_rules([_source(text, "bug", corpus_id=f"blank-{text!r}")])[0]
        assert row.rule_class == "noise"
        assert row.index_in_rag is False


def test_listed_phrases_classify_as_noise_or_churn() -> None:
    """Assertion 6: listed noise and churn phrases, including unequal churn wordings."""
    for text in ("КЛАСС", "Класс!", "ок", "Ок.", "👍"):
        row = apply_feedback_rules([_source(text, "bug")])[0]
        assert row.rule_class == "noise", text
        assert row.index_in_rag is False

    left = "Ниче не работает"
    right = "Ничего не работает"
    assert left != right
    assert normalize_lexicon_key(left) != normalize_lexicon_key(right)
    for text in ("УДАЛЯЮ", "Удаляю", left, right):
        row = apply_feedback_rules([_source(text, "feature", corpus_id=f"churn-{text}")])[0]
        assert row.rule_class == "churn_signal", text
        assert row.index_in_rag is False


def test_bugs_line_3_stays_permissions_bug(assembled_corpus) -> None:
    """Assertion 7: bugs.jsonl line 3 stays a permissions bug and is absent from mismatches."""
    _raw_rows, cleaned_rows = assembled_corpus
    row = _bug_line(cleaned_rows, 3)
    assert row.rule_class == "bug"
    assert row.index_in_rag is True
    assert row.source.scenario_id == "permissions"
    assert row.index_text == row.source.text
    report = build_rule_report(cleaned_rows)
    assert row.source.corpus_id not in {item["corpus_id"] for item in report["mismatches"]}


def test_phone_and_card_are_masked_and_mask_is_stable(assembled_corpus) -> None:
    """Assertion 8: bug lines 4 and 5 are masked, and masking again is a no-op."""
    _raw_rows, cleaned_rows = assembled_corpus
    phone_row = _bug_line(cleaned_rows, 4)
    card_row = _bug_line(cleaned_rows, 5)
    assert PHONE_RE.search(phone_row.source.text)
    assert "+7" in phone_row.source.text
    assert "900" in phone_row.source.text
    assert "[PHONE]" in phone_row.index_text
    assert "+7" not in phone_row.index_text
    assert "900" not in phone_row.index_text
    assert CARD_RE.search(card_row.source.text)
    assert "4242" in card_row.source.text
    assert "[CARD]" in card_row.index_text
    assert "4242" not in card_row.index_text
    assert mask_pii(phone_row.index_text) == phone_row.index_text
    assert mask_pii(card_row.index_text) == card_row.index_text

    sample = "контакт +7 900 000-00-00 и карта 4242 4242 4242 4242"
    masked = mask_pii(sample)
    assert mask_pii(masked) == masked
    assert masked == "контакт [PHONE] и карта [CARD]"


def test_raw_pii_counts_and_index_text_has_no_raw_tokens(assembled_corpus, tmp_path: Path) -> None:
    """Assertion 9: eight raw phones, five raw cards, and no raw tokens in index text."""
    _raw_rows, cleaned_rows = assembled_corpus
    assert len(cleaned_rows) == 510
    phone_hits = sum(len(PHONE_RE.findall(row.source.text)) for row in cleaned_rows)
    card_hits = sum(len(CARD_RE.findall(row.source.text)) for row in cleaned_rows)
    assert phone_hits == 8
    assert card_hits == 5
    for row in cleaned_rows:
        assert "+7" not in row.index_text
        assert "4242" not in row.index_text
    manifest = build_manifest(cleaned_rows, holdout_path=_tiny_holdout(tmp_path))
    assert manifest["pii_raw_counts"] == {"phone": 8, "card": 5}


def test_exact_duplicates_are_suppressed_and_noise_repeats_are_not(assembled_corpus) -> None:
    """Assertion 10: only the ten copies are exact duplicates and index-suppressed."""
    raw_rows, cleaned_rows = assembled_corpus
    assert [row.corpus_id for row in raw_rows if row.is_exact_duplicate] == [copy_id for copy_id, _origin in COPY_PAIRS]
    by_id = {row.source.corpus_id: row for row in cleaned_rows}
    for copy_id, origin_id in COPY_PAIRS:
        copy = by_id[copy_id]
        origin = by_id[origin_id]
        assert copy.rule_class == copy.source.generator_class
        assert copy.index_in_rag is False
        assert copy.rule_reason == "exact_duplicate"
        assert copy.source.duplicate_of == origin_id
        assert origin.index_in_rag is True

    report = build_rule_report(cleaned_rows)
    suppressed = {item["corpus_id"]: item for item in report["index_suppressed"]}
    assert set(suppressed) == {copy_id for copy_id, _origin in COPY_PAIRS}
    for copy_id, origin_id in COPY_PAIRS:
        assert suppressed[copy_id]["duplicate_of"] == origin_id
        assert suppressed[copy_id]["rule_reason"] == "exact_duplicate"
        assert suppressed[copy_id]["rule_class"] == suppressed[copy_id]["generator_class"]

    repeated: list[list[FeedbackCleanedRow]] = []
    grouped: dict[tuple[str, str], list[FeedbackCleanedRow]] = {}
    for row in cleaned_rows:
        if row.rule_class in {"noise", "churn_signal"}:
            grouped.setdefault((row.rule_class, row.source.text), []).append(row)
    repeated.extend(rows for rows in grouped.values() if len(rows) > 1)
    assert repeated
    for rows in repeated:
        assert all(row.rule_reason != "exact_duplicate" for row in rows)
        assert all(row.source.corpus_id not in suppressed for row in rows)


def test_corpus_has_no_class_mismatch_and_fixture_mismatch_keeps_generator(assembled_corpus) -> None:
    """Assertion 11: the built corpus matches; a bug labeled «Класс!» becomes noise."""
    _raw_rows, cleaned_rows = assembled_corpus
    report = build_rule_report(cleaned_rows)
    assert report["class_mismatch_count"] == 0
    assert report["mismatches"] == []

    source = _source("Класс!", "bug", corpus_id="fb-v1-9003", scenario_id="permissions")
    cleaned = apply_feedback_rules([source])[0]
    assert cleaned.rule_class == "noise"
    assert cleaned.index_in_rag is False
    assert cleaned.source.generator_class == "bug"
    assert source.generator_class == "bug"
    mismatch = build_rule_report([cleaned])
    assert mismatch["class_mismatch_count"] == 1
    assert mismatch["mismatches"] == [
        {
            "corpus_id": "fb-v1-9003",
            "generator_class": "bug",
            "rule_class": "noise",
            "rule_reason": cleaned.rule_reason,
            "text_preview": "Класс!",
        }
    ]


def test_index_text_limit_on_corpus_and_long_row_is_not_written(assembled_corpus, tmp_path: Path) -> None:
    """Assertion 12: corpus text stays within 1200; a 1500-character row is truncated aside."""
    raw_rows, cleaned_rows = assembled_corpus
    assert INDEX_TEXT_MAX_CHARS == 1200
    assert all(len(row.index_text) <= 1200 for row in cleaned_rows)
    assert all(row.index_text_truncated is False for row in cleaned_rows)

    marker = "STAGE2_LONG_ROW_"
    text = marker + ("Я" * (1500 - len(marker)))
    assert len(text) == 1500
    long_row = apply_feedback_rules([_source(text, "bug", corpus_id="fb-v1-9004", scenario_id="search")])[0]
    assert long_row.rule_class == "bug"
    assert long_row.index_in_rag is True
    assert long_row.index_text_truncated is True
    assert len(long_row.index_text) == 1200
    assert long_row.index_text == text[:1200]

    out_dir = tmp_path / "corpus"
    write_corpus_files(
        out_dir=out_dir,
        raw_rows=raw_rows,
        cleaned_rows=cleaned_rows,
        holdout_path=_tiny_holdout(tmp_path),
    )
    written = "\n".join(path.read_text(encoding="utf-8") for path in sorted(out_dir.iterdir()))
    assert marker not in written
    assert text not in written
    assert sum(1 for line in (out_dir / "cleaned.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()) == 510


def test_manifest_length_bounds_match_class_lengths(assembled_corpus, tmp_path: Path) -> None:
    """Assertion 13: manifest min/max equals source-text length by rule class."""
    _raw_rows, cleaned_rows = assembled_corpus
    lengths: dict[str, list[int]] = {name: [] for name in ("noise", "churn_signal", "bug", "feature")}
    for row in cleaned_rows:
        lengths[row.rule_class].append(len(row.source.text))
    manifest = build_manifest(cleaned_rows, holdout_path=_tiny_holdout(tmp_path))
    for name, values in lengths.items():
        assert manifest["length"][name] == {"min": min(values), "max": max(values)}
    assert manifest["length"]["noise"] == {"min": 0, "max": 11}
    assert manifest["length"]["churn_signal"] == {"min": 5, "max": 23}
    assert manifest["length"]["bug"]["min"] >= 280
    assert manifest["length"]["bug"]["max"] < 1200
    assert manifest["length"]["feature"]["min"] >= 280
    assert manifest["length"]["feature"]["max"] < 1200


def test_feedback_chunk_content_prefers_mask_over_body() -> None:
    """Assertion 14: chunk content uses index_text, including an empty mask."""
    phone = "+7 900 000-00-00"
    assert feedback_chunk_content(body=phone, index_text="[PHONE]") == "[PHONE]"
    assert feedback_chunk_content(body=phone, index_text="") == ""
    assert phone not in feedback_chunk_content(body=phone, index_text="")
    assert "+7" not in feedback_chunk_content(body=phone, index_text="")
    assert feedback_chunk_content(body="BUG_SHOULD_INDEX", index_text=None) == "BUG_SHOULD_INDEX"


def test_feedback_chunks_use_mask_and_skip_unindexed_without_qdrant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assertion 15: masked bug content is chunked; noise, churn, and duplicates are not."""
    calls: list[str] = []

    def _record(name: str):
        def _inner(*args, **kwargs):  # noqa: ANN001
            del args, kwargs
            calls.append(name)

        return _inner

    monkeypatch.setattr("app.services.document_indexing_service.QdrantStore.ensure_collection", _record("ensure"))
    monkeypatch.setattr("app.services.document_indexing_service.QdrantStore.upsert_chunks", _record("upsert"))
    monkeypatch.setattr("app.clients.qdrant_store.QdrantClient", _record("client"))
    monkeypatch.setattr("app.clients.qdrant_store.QdrantStore.ensure_collection", _record("client-ensure"))
    monkeypatch.setattr("app.clients.qdrant_store.QdrantStore.upsert_chunks", _record("client-upsert"))

    phone = "+7 900 000-00-00"
    masked = "контакт [PHONE]"
    document = DocumentAsset(
        id="doc-chunk",
        tenant_id=TENANT_ID,
        title="feedback",
        file_name="feedback.txt",
        source_type="txt",
        source_path="storage://tenant-stage2/feedback.txt",
        metadata_json={},
        allowed_roles=[],
    )
    rows = [
        FeedbackIndexRow(
            id="noise-row",
            feedback_class="noise",
            body="Класс!",
            index_in_rag=False,
            index_text="Класс!",
            scenario_id=None,
        ),
        FeedbackIndexRow(
            id="churn-row",
            feedback_class="churn_signal",
            body="Удаляю",
            index_in_rag=False,
            index_text="Удаляю",
            scenario_id=None,
        ),
        FeedbackIndexRow(
            id="duplicate-row",
            feedback_class="bug",
            body="DUPLICATE_SHOULD_STAY",
            index_in_rag=False,
            index_text="DUPLICATE_SHOULD_STAY",
            scenario_id="permissions",
        ),
        FeedbackIndexRow(
            id="phone-row",
            feedback_class="bug",
            body=f"контакт {phone}",
            index_in_rag=True,
            index_text=masked,
            scenario_id="reports",
        ),
        FeedbackIndexRow(
            id="plain-row",
            feedback_class="bug",
            body="BUG_SHOULD_INDEX",
            index_in_rag=True,
            index_text=None,
            scenario_id=None,
        ),
    ]
    chunks = _feedback_chunks(document=document, bucket_id=BUCKET_ID, tenant_id=TENANT_ID, rows=rows)
    assert calls == []
    assert [chunk.content for chunk in chunks] == [masked, "BUG_SHOULD_INDEX"]
    assert phone not in chunks[0].content
    assert "+7" not in chunks[0].content
    blob = " ".join(chunk.content for chunk in chunks)
    assert "Класс!" not in blob
    assert "Удаляю" not in blob
    assert "DUPLICATE_SHOULD_STAY" not in blob
    assert chunks[0].metadata["scenario_id"] == "reports"
    assert "scenario_id" not in chunks[1].metadata
    assert all("scenario_id" not in chunk.metadata or chunk.metadata["scenario_id"] is not None for chunk in chunks)


def test_write_corpus_files_keeps_holdout_bytes_and_refuses_holdout_name(
    assembled_corpus,
    tmp_path: Path,
) -> None:
    """Assertion 16: real holdout bytes stay put; writing the holdout name is refused."""
    raw_rows, cleaned_rows = assembled_corpus
    before = HOLDOUT_PATH.read_bytes()
    assert _sha256(HOLDOUT_PATH) == EXPECTED_HOLDOUT_SHA256
    assert _nonempty_lines(HOLDOUT_PATH) == 20

    out_dir = tmp_path / "v1-out"
    write_corpus_files(
        out_dir=out_dir,
        raw_rows=raw_rows,
        cleaned_rows=cleaned_rows,
        holdout_path=HOLDOUT_PATH,
    )
    assert HOLDOUT_PATH.read_bytes() == before
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["holdout_rows"] == 20
    assert manifest["holdout_sha256"] == EXPECTED_HOLDOUT_SHA256
    assert manifest["holdout_sha256"] == hashlib.sha256(before).hexdigest()

    sentinel = tmp_path / "holdout.jsonl"
    sentinel.write_text("do-not-touch\n", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to open holdout.jsonl for writing"):
        _refuse_holdout_write(sentinel, tmp_path / "other-name.jsonl")
    assert sentinel.read_text(encoding="utf-8") == "do-not-touch\n"

    collision = tmp_path / "collision"
    collision.mkdir()
    blocked = collision / "manifest.json"
    blocked.write_bytes(b"SENTINEL")
    with pytest.raises(ValueError, match="refusing to open holdout.jsonl for writing"):
        write_corpus_files(
            out_dir=collision,
            raw_rows=raw_rows,
            cleaned_rows=cleaned_rows,
            holdout_path=blocked,
        )
    assert blocked.read_bytes() == b"SENTINEL"


def test_manifest_sources_stay_on_the_assembly_that_built_the_rows(assembled_corpus, tmp_path: Path) -> None:
    """Assertion 17: a later assembly cannot replace or lend source hashes."""
    raw_a, cleaned_a = assembled_corpus
    holdout = _tiny_holdout(tmp_path)
    manifest_a = build_manifest(cleaned_a, holdout_path=holdout)
    sha_a = _source_sha(manifest_a, "noise.jsonl")
    assert sha_a == _sha256(INPUTS["noise"])

    paths_b = _copy_inputs(tmp_path / "assembly-b", noise_suffix=" ")
    raw_b = _assemble_from(paths_b)
    cleaned_b = apply_feedback_rules(raw_b)
    manifest_b = build_manifest(cleaned_b, holdout_path=holdout)
    sha_b = _source_sha(manifest_b, "noise.jsonl")
    assert sha_b == _sha256(paths_b["noise"])
    assert sha_b != sha_a
    again = build_manifest(cleaned_a, holdout_path=holdout)
    assert again["sources"] == manifest_a["sources"]

    foreign = _source("ок", "noise", scenario_id=None)
    with pytest.raises(ValueError) as foreign_error:
        build_manifest([_cleaned_from(foreign)], holdout_path=holdout)
    assert sha_a not in str(foreign_error.value)
    assert sha_b not in str(foreign_error.value)

    cloned = replace(cleaned_a[0].source)
    assert cloned == cleaned_a[0].source
    assert cloned is not cleaned_a[0].source
    with pytest.raises(ValueError) as clone_error:
        build_manifest([_cleaned_from(cloned)], holdout_path=holdout)
    assert sha_a not in str(clone_error.value)
    assert sha_b not in str(clone_error.value)

    with pytest.raises(ValueError) as mixed_error:
        build_manifest([cleaned_a[0], cleaned_b[0]], holdout_path=holdout)
    assert sha_a not in str(mixed_error.value)
    assert sha_b not in str(mixed_error.value)

    out_dir = tmp_path / "mixed-out"
    with pytest.raises(ValueError) as write_error:
        write_corpus_files(
            out_dir=out_dir,
            raw_rows=raw_a,
            cleaned_rows=cleaned_b,
            holdout_path=holdout,
        )
    assert sha_a not in str(write_error.value)
    assert sha_b not in str(write_error.value)
    assert not (out_dir / "manifest.json").exists()


def test_jsonl_build_does_not_open_postgres(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Assertion 17: writing jsonl does not open Postgres."""
    opened = _forbid_database(monkeypatch)

    async def _no_seed(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("seed started during jsonl build")

    monkeypatch.setattr("scripts.build_feedback_corpus._seed", _no_seed)
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_feedback_corpus.py",
            "--write-jsonl",
            "--out-dir",
            str(tmp_path / "jsonl"),
            "--holdout-path",
            str(HOLDOUT_PATH),
            "--noise-path",
            str(INPUTS["noise"]),
            "--churn-path",
            str(INPUTS["churn"]),
            "--bugs-path",
            str(INPUTS["bugs"]),
            "--features-path",
            str(INPUTS["features"]),
        ],
    )
    main()
    assert opened == []
    written = tmp_path / "jsonl"
    assert (written / "raw.jsonl").is_file()
    assert (written / "cleaned.jsonl").is_file()
    assert _nonempty_lines(written / "cleaned.jsonl") == 510
    assert _sha256(HOLDOUT_PATH) == EXPECTED_HOLDOUT_SHA256


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--tenant-id", "tenant-stage2"],
        ["--bucket-id", "bucket-stage2"],
        ["--tenant-id", "   ", "--bucket-id", "bucket-stage2"],
        ["--tenant-id", "tenant-stage2", "--bucket-id", "   "],
        ["--tenant-id", "local_demo"],
    ],
)
def test_seed_cli_requires_both_ids_without_default_tenant(
    monkeypatch: pytest.MonkeyPatch,
    extra: list[str],
) -> None:
    """Assertion 17: --seed without both ids exits and does not use the default tenant."""
    opened = _forbid_database(monkeypatch)
    seeded: list[tuple[str, str]] = []

    async def fake_seed(tenant_id: str, bucket_id: str, cleaned_rows) -> None:  # noqa: ANN001
        del cleaned_rows
        seeded.append((tenant_id, bucket_id))

    monkeypatch.setattr("scripts.build_feedback_corpus._seed", fake_seed)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(
            postgres_dsn="postgresql+asyncpg://blocked/no",
            default_tenant_id="local_demo",
            default_bucket_id="taskflow_seed",
        ),
    )
    monkeypatch.setattr("sys.argv", ["build_feedback_corpus.py", "--seed", *extra])
    with pytest.raises(SystemExit):
        main()
    assert seeded == []
    assert opened == []


def test_seed_cli_passes_explicit_ids_not_default_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assertion 17: explicit --tenant-id and --bucket-id reach seed unchanged."""
    opened = _forbid_database(monkeypatch)
    seen: dict[str, object] = {}

    async def fake_seed(tenant_id: str, bucket_id: str, cleaned_rows) -> None:  # noqa: ANN001
        seen["tenant_id"] = tenant_id
        seen["bucket_id"] = bucket_id
        seen["rows"] = len(cleaned_rows)

    monkeypatch.setattr("scripts.build_feedback_corpus._seed", fake_seed)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(
            postgres_dsn="postgresql+asyncpg://blocked/no",
            default_tenant_id="local_demo",
            default_bucket_id="taskflow_seed",
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_feedback_corpus.py",
            "--seed",
            "--tenant-id",
            "tenant-stage2",
            "--bucket-id",
            "bucket-stage2",
        ],
    )
    main()
    assert seen == {"tenant_id": "tenant-stage2", "bucket_id": "bucket-stage2", "rows": 510}
    assert opened == []


def test_seed_on_sqlite_rewrites_same_bucket_and_keeps_other_rows(
    assembled_corpus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assertion 17: repeat seed keeps corpus ids and uuid5; other rows stay."""
    _raw_rows, cleaned_rows = assembled_corpus
    engine = _memory_engine()
    try:
        with Session(engine) as session:
            _add_bucket(session, bucket_id=BUCKET_ID, tenant_id=TENANT_ID, name="feedback")
            _add_bucket(session, bucket_id=OTHER_BUCKET_ID, tenant_id=TENANT_ID, name="other")
            session.commit()
        with Session(engine) as session:
            session.add(
                FeedbackItem(
                    id="keep-no-corpus",
                    tenant_id=TENANT_ID,
                    bucket_id=BUCKET_ID,
                    document_id=None,
                    feedback_class="noise",
                    body="KEEP_NO_CORPUS",
                    index_in_rag=False,
                )
            )
            session.add(
                FeedbackItem(
                    id="keep-other-bucket",
                    tenant_id=TENANT_ID,
                    bucket_id=OTHER_BUCKET_ID,
                    document_id=None,
                    feedback_class="bug",
                    body="KEEP_OTHER_BUCKET",
                    index_in_rag=False,
                    corpus_id="fb-v1-0001",
                    generator_class="bug",
                    rule_class="bug",
                    rule_reason="keep_generator",
                )
            )
            session.commit()

        opened = _install_sqlite_seed(monkeypatch, engine)
        asyncio.run(_seed(TENANT_ID, BUCKET_ID, cleaned_rows))
        assert opened == ["postgresql+asyncpg://po_user:po_password@127.0.0.1:1/not_dialed"]

        expected_ids = {
            row.source.corpus_id: str(
                uuid5(NAMESPACE_URL, f"feedback-v1:{TENANT_ID}:{BUCKET_ID}:{row.source.corpus_id}")
            )
            for row in cleaned_rows
        }
        phone_row = _bug_line(cleaned_rows, 4)

        def _seeded() -> list[dict[str, object]]:
            with Session(engine) as session:
                rows = session.scalars(
                    select(FeedbackItem).where(
                        FeedbackItem.tenant_id == TENANT_ID,
                        FeedbackItem.bucket_id == BUCKET_ID,
                        FeedbackItem.corpus_id.is_not(None),
                    )
                ).all()
                return [
                    {
                        "id": row.id,
                        "corpus_id": row.corpus_id,
                        "document_id": row.document_id,
                        "tenant_id": row.tenant_id,
                        "body": row.body,
                        "index_text": row.index_text,
                        "index_in_rag": row.index_in_rag,
                    }
                    for row in rows
                ]

        seeded = _seeded()
        assert len(seeded) == 510
        assert {row["corpus_id"]: row["id"] for row in seeded} == expected_ids
        assert all(row["document_id"] is None for row in seeded)
        assert all(row["tenant_id"] == TENANT_ID for row in seeded)
        stored_phone = next(row for row in seeded if row["corpus_id"] == phone_row.source.corpus_id)
        assert stored_phone["body"] == phone_row.source.text
        assert "+7" in str(stored_phone["body"])
        assert stored_phone["index_text"] == phone_row.index_text
        assert "[PHONE]" in str(stored_phone["index_text"])
        assert "+7" not in str(stored_phone["index_text"])
        assert stored_phone["index_in_rag"] is True
        first_ids = {row["corpus_id"]: row["id"] for row in seeded}

        with Session(engine) as session:
            mutated = session.scalar(
                select(FeedbackItem).where(
                    FeedbackItem.bucket_id == BUCKET_ID,
                    FeedbackItem.corpus_id == "fb-v1-0001",
                )
            )
            assert mutated is not None
            mutated.body = "MUTATED"
            session.commit()

        asyncio.run(_seed(TENANT_ID, BUCKET_ID, cleaned_rows))
        reseeded = _seeded()
        assert len(reseeded) == 510
        assert {row["corpus_id"]: row["id"] for row in reseeded} == first_ids == expected_ids
        restored = next(row for row in reseeded if row["corpus_id"] == "fb-v1-0001")
        assert restored["body"] != "MUTATED"
        assert restored["body"] == next(row.source.text for row in cleaned_rows if row.source.corpus_id == "fb-v1-0001")
        assert all(row["document_id"] is None for row in reseeded)

        with Session(engine) as session:
            kept = session.get(FeedbackItem, "keep-no-corpus")
            other = session.get(FeedbackItem, "keep-other-bucket")
            assert kept is not None and kept.corpus_id is None and kept.body == "KEEP_NO_CORPUS"
            assert kept.bucket_id == BUCKET_ID
            assert other is not None
            assert other.bucket_id == OTHER_BUCKET_ID
            assert other.corpus_id == "fb-v1-0001"
            assert other.body == "KEEP_OTHER_BUCKET"
            assert other.id == "keep-other-bucket"
    finally:
        engine.dispose()


def test_seed_on_sqlite_rejects_mismatched_tenant_without_writing(
    assembled_corpus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assertion 17: a foreign tenant or another tenant's bucket does not change rows."""
    _raw_rows, cleaned_rows = assembled_corpus
    engine = _memory_engine()
    try:
        with Session(engine) as session:
            _add_bucket(session, bucket_id=BUCKET_ID, tenant_id=TENANT_ID, name="feedback")
            _add_bucket(session, bucket_id=FOREIGN_BUCKET_ID, tenant_id=OTHER_TENANT_ID, name="foreign")
            session.commit()
        with Session(engine) as session:
            session.add(
                FeedbackItem(
                    id="owned-row",
                    tenant_id=TENANT_ID,
                    bucket_id=BUCKET_ID,
                    document_id=None,
                    feedback_class="noise",
                    body="OWNED",
                    index_in_rag=False,
                    corpus_id="fb-v1-0001",
                )
            )
            session.add(
                FeedbackItem(
                    id="foreign-row",
                    tenant_id=OTHER_TENANT_ID,
                    bucket_id=FOREIGN_BUCKET_ID,
                    document_id=None,
                    feedback_class="bug",
                    body="FOREIGN",
                    index_in_rag=False,
                    corpus_id="fb-v1-0001",
                    generator_class="bug",
                    rule_class="bug",
                    rule_reason="keep_generator",
                )
            )
            session.commit()
        before = _feedback_snapshot(engine)
        _install_sqlite_seed(monkeypatch, engine)
        with pytest.raises(SystemExit):
            asyncio.run(_seed(OTHER_TENANT_ID, BUCKET_ID, cleaned_rows))
        with pytest.raises(SystemExit):
            asyncio.run(_seed(TENANT_ID, FOREIGN_BUCKET_ID, cleaned_rows))
        with pytest.raises(SystemExit):
            asyncio.run(_seed(TENANT_ID, "missing-bucket", cleaned_rows))
        assert _feedback_snapshot(engine) == before
    finally:
        engine.dispose()


def test_stage1_checks_still_reject_noise_index_and_allow_old_insert() -> None:
    """Assertion 18: stage 1 CHECKs stay, and an insert without the new columns works."""
    migration = MIGRATION_0010.read_text(encoding="utf-8")
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in FeedbackItem.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert checks["ck_feedback_items_feedback_class"] == CLASS_CHECK
    assert checks["ck_feedback_items_index_in_rag_class"] == INDEX_CHECK
    assert CLASS_CHECK in migration
    assert INDEX_CHECK in migration
    assert "feedback_items" not in DEFAULT_SQL_TOOL_ALLOWED_TABLES
    assert "feedback_items" not in build_schema_card(allowed_tables=DEFAULT_SQL_TOOL_ALLOWED_TABLES)

    engine = _memory_engine()
    try:
        with Session(engine) as session:
            _add_bucket(session, bucket_id=BUCKET_ID, tenant_id=TENANT_ID, name="feedback")
            session.add(
                DocumentAsset(
                    id="doc-stage1",
                    tenant_id=TENANT_ID,
                    owner_user_id="owner",
                    title="notes.txt",
                    file_name="notes.txt",
                    source_type="txt",
                    source_path="storage://tenant-stage2/notes.txt",
                    status="uploaded",
                    visibility="private",
                    allowed_roles=[],
                    size_bytes=1,
                    metadata_json={},
                )
            )
            session.commit()
        with engine.connect() as connection:
            ddl = connection.execute(text("SELECT sql FROM sqlite_master WHERE name='feedback_items'")).scalar_one()
        assert "ck_feedback_items_feedback_class" in ddl
        assert "ck_feedback_items_index_in_rag_class" in ddl
        assert CLASS_CHECK in ddl
        assert INDEX_CHECK in ddl

        with Session(engine) as session:
            session.add(
                FeedbackItem(
                    id="bad-class",
                    tenant_id=TENANT_ID,
                    bucket_id=BUCKET_ID,
                    document_id="doc-stage1",
                    feedback_class="praise",
                    body="not a class",
                    index_in_rag=False,
                )
            )
            with pytest.raises(IntegrityError, match="ck_feedback_items_feedback_class"):
                session.commit()
            session.rollback()

        with Session(engine) as session:
            session.add(
                FeedbackItem(
                    id="noise-indexed",
                    tenant_id=TENANT_ID,
                    bucket_id=BUCKET_ID,
                    document_id="doc-stage1",
                    feedback_class="noise",
                    body="should stay out of qdrant",
                    index_in_rag=True,
                )
            )
            with pytest.raises(IntegrityError, match="ck_feedback_items_index_in_rag_class"):
                session.commit()
            session.rollback()

        with Session(engine) as session:
            row = FeedbackItem(
                id="stage1-shape",
                tenant_id=TENANT_ID,
                bucket_id=BUCKET_ID,
                document_id="doc-stage1",
                feedback_class="noise",
                body="stage 1 row",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            assert row.index_in_rag is False
            assert row.generator_class is None
            assert row.rule_class is None
            assert row.scenario_id is None
            assert row.index_text is None
            assert row.corpus_id is None
            assert row.rule_reason is None
            assert row.duplicate_of is None
    finally:
        engine.dispose()


def test_app_source_has_no_index_in_rag_true_literal() -> None:
    """Assertion 18: backend/app does not contain an index_in_rag=True literal."""
    hits: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        text_value = path.read_text(encoding="utf-8")
        if "index_in_rag=True" in text_value or "index_in_rag = True" in text_value:
            hits.append(str(path.relative_to(BACKEND_ROOT)))
    assert hits == []

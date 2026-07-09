from app.models.chat import SourceChunk
from app.services.rag_service import (
    _apply_source_diversity,
    _docx_neighbor_sources,
    _docx_rerank_score,
    _extract_exact_numeric_terms,
    _extract_docx_exact_terms,
    _filter_sources_by_score,
    _looks_like_document_header_question,
    _remove_numeric_metric_lines,
    _required_source_types_for_supplement,
)


def _source(
    id: str,
    *,
    score: float | None = 1.0,
    title: str = "Source",
    source_type: str = "markdown",
    source_path: str = "/tmp/source.md",
    content: str | None = None,
    metadata: dict[str, object] | None = None,
) -> SourceChunk:
    return SourceChunk(
        id=id,
        score=score,
        title=title,
        source_type=source_type,
        source_path=source_path,
        feature=[],
        content=content or f"content {id}",
        metadata=metadata or {},
    )


def test_filter_sources_by_score_keeps_sources_at_or_above_threshold() -> None:
    sources = [
        _source("low", score=0.59),
        _source("edge", score=0.60),
        _source("high", score=0.75),
        _source("missing", score=None),
    ]

    kept = _filter_sources_by_score(sources, 0.60)

    assert [source.id for source in kept] == ["edge", "high"]


def test_source_diversity_limits_duplicate_titles() -> None:
    sources = [
        _source("1", title="Same title"),
        _source("2", title="Same title"),
        _source("3", title="Other title"),
    ]

    kept = _apply_source_diversity(
        sources,
        max_sources_per_title=1,
        max_sources_per_source_type=None,
        max_sources_per_source_path=None,
    )

    assert [source.id for source in kept] == ["1", "3"]


def test_required_source_types_include_explicit_document_scope_types() -> None:
    required = _required_source_types_for_supplement(
        routing_hints={},
        selected_source_types=["docx", "image_digest", "image_ocr"],
        selected_document_ids=[],
        selected_source_paths=["/tmp/sample.docx"],
    )

    assert required == ["docx", "image_digest", "image_ocr"]


def test_remove_numeric_metric_lines_keeps_qualitative_context() -> None:
    text = "\n".join(
        [
            "Metric: adoption dropped by 12%",
            "Root cause: delayed Slack delivery.",
            "Latency metric: 1400 ms",
        ]
    )

    sanitized = _remove_numeric_metric_lines(text)

    assert "Root cause" in sanitized
    assert "12%" not in sanitized
    assert "1400 ms" not in sanitized


def test_extract_exact_numeric_terms_for_excel_identifiers() -> None:
    terms = _extract_exact_numeric_terms(
        "Найди штрихкод 4600682643425 и строку 123."
    )

    assert terms == ["4600682643425"]


def test_document_header_question_detection_is_not_triggered_by_price_word_only() -> None:
    assert _looks_like_document_header_question(
        "Что это за документ и какая организация указана?"
    )
    assert not _looks_like_document_header_question(
        "Какие позиции Жатецкий Гусь видны в прайсе?"
    )


def test_extract_docx_exact_terms_keeps_code_tokens_without_docx_noise() -> None:
    terms = _extract_docx_exact_terms(
        "По Front&Back_C#.docx найди async Task ModifyUsers и React задания."
    )

    assert "async" in terms
    assert "task" in terms
    assert "modifyusers" in terms
    assert "react" in terms
    assert "docx" not in terms


def test_docx_neighbor_sources_finds_adjacent_paragraphs_and_windows() -> None:
    seed = _source(
        "p10",
        source_type="docx",
        metadata={"document_metadata": {"block_type": "paragraph", "paragraph_index": 10}},
    )
    previous = _source(
        "p9",
        source_type="docx",
        metadata={"document_metadata": {"block_type": "paragraph", "paragraph_index": 9}},
    )
    far = _source(
        "p20",
        source_type="docx",
        metadata={"document_metadata": {"block_type": "paragraph", "paragraph_index": 20}},
    )
    window = _source(
        "w",
        source_type="docx",
        metadata={
            "document_metadata": {
                "block_type": "paragraph_window",
                "paragraph_start_index": 8,
                "paragraph_end_index": 12,
            }
        },
    )

    neighbors = _docx_neighbor_sources(
        seed_sources=[seed],
        candidates=[far, window, previous],
        radius=2,
    )

    assert [source.id for source in neighbors] == ["w", "p9"]


def test_docx_rerank_score_boosts_exact_code_matches() -> None:
    terms = ["modifyusers", "async"]
    weak = _source(
        "weak",
        score=0.80,
        source_type="docx",
        content="File: Front&Back_C#.docx\nCurrent paragraph: unrelated task",
        metadata={"document_metadata": {"block_type": "paragraph", "paragraph_index": 1}},
    )
    exact = _source(
        "exact",
        score=0.75,
        source_type="docx",
        content=(
            "File: Front&Back_C#.docx\n"
            "Current paragraph: async Task ModifyUsers(int userId)"
        ),
        metadata={"document_metadata": {"block_type": "paragraph", "paragraph_index": 2}},
    )

    assert _docx_rerank_score(exact, terms) > _docx_rerank_score(weak, terms)

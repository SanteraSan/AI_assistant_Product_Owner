from app.models.chat import SourceChunk
from app.services.rag_service import (
    _apply_source_diversity,
    _extract_exact_numeric_terms,
    _filter_sources_by_score,
    _looks_like_document_header_question,
    _remove_numeric_metric_lines,
)


def _source(
    id: str,
    *,
    score: float | None = 1.0,
    title: str = "Source",
    source_type: str = "markdown",
    source_path: str = "/tmp/source.md",
) -> SourceChunk:
    return SourceChunk(
        id=id,
        score=score,
        title=title,
        source_type=source_type,
        source_path=source_path,
        feature=[],
        content=f"content {id}",
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

from app.models.chat import SourceChunk
from app.db.models import ChatSession
from app.services.chat_history_service import _apply_session_context
from app.services.rag_service import (
    _apply_source_diversity,
    _docx_neighbor_sources,
    _docx_rerank_score,
    _excel_exact_match_count,
    _extract_excel_exact_terms,
    _extract_exact_numeric_terms,
    _extract_docx_exact_terms,
    _extract_requested_file_names,
    _filter_sources_by_score,
    _is_narrow_document_scope,
    _looks_like_document_header_question,
    _lower_score_threshold,
    _missing_requested_file_answer,
    _missing_requested_file_names,
    _remove_numeric_metric_lines,
    _required_source_types_for_supplement,
    build_rag_prompt,
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


def test_narrow_document_scope_can_lower_score_threshold() -> None:
    assert _is_narrow_document_scope(bucket_ids=[], document_ids=["doc-1"], source_paths=[])
    assert _is_narrow_document_scope(
        bucket_ids=["bucket-1"], document_ids=[], source_paths=[]
    )
    assert _is_narrow_document_scope(
        bucket_ids=[], document_ids=["doc-1", "doc-2"], source_paths=["/tmp/a.md"]
    )
    assert not _is_narrow_document_scope(bucket_ids=[], document_ids=[], source_paths=[])
    assert not _is_narrow_document_scope(
        bucket_ids=["bucket-1", "bucket-2"],
        document_ids=["doc-1", "doc-2", "doc-3"],
        source_paths=[],
    )
    assert _lower_score_threshold(0.68, 0.45) == 0.45


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
        selected_bucket_ids=[],
        selected_document_ids=[],
        selected_source_paths=["/tmp/sample.docx"],
    )

    assert required == ["docx", "image_digest", "image_ocr"]


def test_required_source_types_include_selected_bucket_scope_types() -> None:
    required = _required_source_types_for_supplement(
        routing_hints={},
        selected_source_types=["excel_chart", "image_digest"],
        selected_bucket_ids=["bucket-1"],
        selected_document_ids=[],
        selected_source_paths=[],
    )

    assert required == ["excel_chart", "image_digest"]


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


def test_rag_prompt_prioritizes_current_context_over_memory_and_product_scope() -> None:
    prompt = build_rag_prompt(
        question="Что в выбранном bucket написано про слонов?",
        sources=[
            _source(
                "joke",
                title="Шутки",
                source_type="txt",
                content="Слоны не летают потому что они тяжелые, а размах ушей не слишком большой!",
            )
        ],
        memory_context={
            "used": True,
            "content": "Раньше данных про слонов не было.",
        },
    )

    assert "не отменяет актуальный блок Контекст" in prompt
    assert "даже если документ не относится к продукту TaskFlow AI" in prompt
    assert "не отказывайся отвечать только из-за типа источника" in prompt
    assert "Слоны не летают" in prompt


def test_missing_requested_file_names_detects_absent_image() -> None:
    sources = [
        _source(
            "docx-image",
            title="sample-with-images.docx",
            source_type="docx_image_digest",
            source_path="/tmp/sample-with-images.docx",
            metadata={"document_metadata": {"document_file_name": "sample-with-images.docx"}},
        )
    ]
    message = (
        "Расскажи что ты видишь на картинке moto.jpg в доступных документах, "
        "если он у тебя там есть"
    )

    assert _extract_requested_file_names(message) == ["moto.jpg"]
    assert _missing_requested_file_names(message, sources) == ["moto.jpg"]
    assert "moto.jpg" in _missing_requested_file_answer(["moto.jpg"])
    assert _missing_requested_file_names(
        "Опиши sample-with-images.docx",
        sources,
    ) == []


def test_rag_prompt_includes_document_file_name_in_source_header() -> None:
    prompt = build_rag_prompt(
        question="О чем написано в файле AGENTS.md?",
        sources=[
            _source(
                "agents",
                title="AI Development Rules For Product Owner Assistant",
                source_type="md",
                content="# AI Development Rules For Product Owner Assistant",
                metadata={
                    "document_metadata": {
                        "document_file_name": "AGENTS.md",
                    }
                },
            )
        ],
    )

    assert "file=AGENTS.md" in prompt
    assert "Не говори, что файл отсутствует" in prompt
    assert "не упоминай другие файлы" in prompt
    assert "который отвечает по пользовательским документам" in prompt


def test_rag_prompt_asks_for_compact_answers() -> None:
    prompt = build_rag_prompt(
        question="Кратко: о чём файл?",
        sources=[_source("doc", content="Файл про правила разработки.")],
    )

    assert "Пиши кратко и по делу" in prompt
    assert "короткий grounded-ответ" in prompt
    assert "Не перечисляй источники" in prompt
    assert "CHUNK" in prompt
    assert "1–3 реально использованных источника" not in prompt


def test_metadata_string_list_dedupes_and_skips_invalid_values() -> None:
    from app.services.chat_history_service import _metadata_string_list

    values = _metadata_string_list(
        {
            "attached_document_ids": ["doc-1", " doc-1 ", "", "doc-2", 3, None, "doc-2"],
        },
        "attached_document_ids",
    )

    assert values == ["doc-1", "doc-2"]


def test_chat_session_context_uses_active_bucket_separately_from_retrieval_scope() -> None:
    session = ChatSession(id="session-1", title="chat", active_bucket_id="bucket-a")

    _apply_session_context(
        session,
        {
            "active_bucket_id": "bucket-a",
            "bucket_ids": [],
            "document_ids": ["doc-1"],
            "model_id": "qwen3.5:9b",
            "approach": "hybrid",
        },
    )

    assert session.active_bucket_id == "bucket-a"
    assert session.model_id == "qwen3.5:9b"
    assert session.approach == "hybrid"


def test_extract_exact_numeric_terms_for_excel_identifiers() -> None:
    terms = _extract_exact_numeric_terms(
        "Найди штрихкод 4600682643425 и строку 123."
    )

    assert terms == ["4600682643425"]


def test_extract_excel_exact_terms_keeps_product_names_without_question_noise() -> None:
    terms = _extract_excel_exact_terms(
        "Что известно из hard_for_analis.xls про ПЯТНИЦКОЕ НЕФИЛЬТРОВАННОЕ: город и цену?"
    )

    assert "пятницкое" in terms
    assert "нефильтрованное" in terms
    assert "hard_for_analis" not in terms
    assert "город" not in terms
    assert "цену" not in terms


def test_extract_excel_exact_terms_keeps_short_product_numbers() -> None:
    terms = _extract_excel_exact_terms(
        "Что на картинке, где указано 4,1 % алкоголь, 11% плотность и 3500 р.?"
    )

    assert "4,1" in terms
    assert "11" in terms
    assert "3500" in terms
    assert "картинке" not in terms
    assert "алкоголь" not in terms
    assert "плотность" not in terms


def test_excel_exact_match_count_boosts_product_row() -> None:
    terms = ["пятницкое", "нефильтрованное", "алкоголь"]
    generic = _source(
        "generic",
        source_type="excel_row",
        content="Срок годности 30 суток. Объем 50 л. Цена за кегу 3500 р.",
    )
    product = _source(
        "product",
        source_type="excel_row",
        content="ПЯТНИЦКОЕ НЕФИЛЬТРОВАННОЕ 4,1 % алкоголь, цена за кегу 3500 р.",
    )

    assert _excel_exact_match_count(product, terms) > _excel_exact_match_count(generic, terms)


def test_excel_exact_match_count_boosts_xlsx_anchor_image_row() -> None:
    terms = _extract_excel_exact_terms("4,1 % алкоголь, 11% плотность, 3500 р.")
    weak = _source(
        "weak",
        source_type="image_digest",
        content="Linked text: 4,0 % алкоголь, 11% плотность. Цена за кегу 3250 р.",
    )
    target = _source(
        "target",
        source_type="image_digest",
        content="Linked text: ПЯТНИЦКОЕ 4,1 % алкоголь, 11% плотность. Цена за кегу 3500 р.",
    )

    assert _excel_exact_match_count(target, terms) > _excel_exact_match_count(weak, terms)


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

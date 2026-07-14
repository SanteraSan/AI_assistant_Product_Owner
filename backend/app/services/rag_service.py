import re
from dataclasses import dataclass
from time import perf_counter

from app.clients.qdrant_store import QdrantStore
from app.models.chat import RagChatResponse, SourceChunk
from app.services.feature_extractor import FeatureExtractor
from app.services.ollama_client import OllamaClient
from app.services.query_router import QueryRouter


@dataclass(frozen=True)
class RagSearchResult:
    sources: list[SourceChunk]
    features: list[str]
    source_types: list[str]
    score_threshold: float | None
    retrieval: dict[str, object]
    query_hints: dict[str, object]
    latency_ms: int


class RagService:
    def __init__(
        self,
        *,
        ollama_client: OllamaClient,
        qdrant_store: QdrantStore,
        feature_extractor: FeatureExtractor,
        query_router: QueryRouter,
        embedding_model: str,
        default_model: str,
        default_top_k: int,
        default_score_threshold: float | None,
        candidate_multiplier: int,
        generation_keep_alive: str,
        generation_temperature: float,
        generation_top_p: float,
        excel_supplement_scroll_limit: int,
        docx_supplement_scroll_limit: int,
    ) -> None:
        self._ollama_client = ollama_client
        self._qdrant_store = qdrant_store
        self._feature_extractor = feature_extractor
        self._query_router = query_router
        self._embedding_model = embedding_model
        self._default_model = default_model
        self._default_top_k = default_top_k
        self._default_score_threshold = default_score_threshold
        self._candidate_multiplier = candidate_multiplier
        self._generation_keep_alive = generation_keep_alive
        self._generation_temperature = generation_temperature
        self._generation_top_p = generation_top_p
        self._excel_supplement_scroll_limit = excel_supplement_scroll_limit
        self._docx_supplement_scroll_limit = docx_supplement_scroll_limit

    async def search(
        self,
        *,
        query: str,
        top_k: int | None = None,
        score_threshold: float | None = None,
        tenant_id: str | None = None,
        bucket_ids: list[str] | None = None,
        features: list[str] | None = None,
        source_types: list[str] | None = None,
        document_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        allowed_source_paths: list[str] | None = None,
        max_sources_per_title: int | None = None,
        max_sources_per_source_type: int | None = None,
        max_sources_per_source_path: int | None = None,
    ) -> RagSearchResult:
        """Retrieve evidence chunks without LLM generation (for tools/agents)."""
        selected_top_k = top_k or self._default_top_k
        selected_score_threshold = (
            score_threshold if score_threshold is not None else self._default_score_threshold
        )
        candidate_k = selected_top_k * self._candidate_multiplier
        selected_tenant_id = tenant_id.strip() if tenant_id else None
        selected_bucket_ids = _normalize_values(bucket_ids or [])
        selected_features = _normalize_features(features or [])
        selected_source_types = _normalize_values(source_types or [])
        selected_document_ids = _normalize_values(document_ids or [])
        selected_source_paths = _normalize_values(source_paths or [])
        selected_allowed_source_paths = _normalize_values(allowed_source_paths or [])
        has_document_filter = bool(
            selected_document_ids or selected_source_paths or selected_allowed_source_paths
        )
        if not selected_features and not has_document_filter:
            selected_features = self._feature_extractor.extract(query)
        routing_decision = self._query_router.route(
            message=query,
            source_types=selected_source_types,
            score_threshold=selected_score_threshold,
            user_provided_source_types=bool(source_types),
            user_provided_score_threshold=score_threshold is not None,
        )
        selected_source_types = routing_decision.source_types
        selected_score_threshold = routing_decision.score_threshold
        if score_threshold is None and _is_narrow_document_scope(
            bucket_ids=selected_bucket_ids,
            document_ids=selected_document_ids,
            source_paths=selected_source_paths,
        ):
            selected_score_threshold = _lower_score_threshold(selected_score_threshold, 0.45)

        started_at = perf_counter()
        query_vector = await self._ollama_client.embed(self._embedding_model, query)
        sources, required_source_types, excel_supplement_count, docx_supplement_count = (
            self._retrieve_sources(
                query_vector=query_vector,
                message=query,
                candidate_k=candidate_k,
                selected_top_k=selected_top_k,
                selected_score_threshold=selected_score_threshold,
                selected_tenant_id=selected_tenant_id,
                selected_bucket_ids=selected_bucket_ids,
                selected_features=selected_features,
                selected_source_types=selected_source_types,
                selected_document_ids=selected_document_ids,
                selected_source_paths=selected_source_paths,
                selected_allowed_source_paths=selected_allowed_source_paths,
                routing_hints=routing_decision.hints,
            )
        )
        sources = _apply_source_diversity(
            sources,
            max_sources_per_title=max_sources_per_title if max_sources_per_title is not None else 1,
            max_sources_per_source_type=max_sources_per_source_type,
            max_sources_per_source_path=max_sources_per_source_path,
        )
        sources = sources[:selected_top_k]
        latency_ms = int((perf_counter() - started_at) * 1000)
        return RagSearchResult(
            sources=sources,
            features=selected_features,
            source_types=selected_source_types,
            score_threshold=selected_score_threshold,
            retrieval={
                "requested_top_k": selected_top_k,
                "candidate_k": candidate_k,
                "retrieval_query": query,
                "required_source_types": required_source_types,
                "tenant_id": selected_tenant_id,
                "bucket_ids": selected_bucket_ids,
                "document_ids": selected_document_ids,
                "source_paths": selected_source_paths,
                "allowed_source_paths": selected_allowed_source_paths,
                "excel_supplement_count": excel_supplement_count,
                "docx_supplement_count": docx_supplement_count,
                "final_top_k": len(sources),
            },
            query_hints=routing_decision.hints,
            latency_ms=latency_ms,
        )

    async def answer(
        self,
        message: str,
        model: str | None = None,
        retrieval_query: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
        tenant_id: str | None = None,
        bucket_ids: list[str] | None = None,
        features: list[str] | None = None,
        source_types: list[str] | None = None,
        document_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        allowed_source_paths: list[str] | None = None,
        max_sources_per_title: int | None = None,
        max_sources_per_source_type: int | None = None,
        max_sources_per_source_path: int | None = None,
        memory_context: dict[str, object] | None = None,
        additional_sources: list[SourceChunk] | None = None,
    ) -> RagChatResponse:
        selected_model = model or self._default_model
        selected_retrieval_query = retrieval_query or message
        started_at = perf_counter()
        search = await self.search(
            query=selected_retrieval_query,
            top_k=top_k,
            score_threshold=score_threshold,
            tenant_id=tenant_id,
            bucket_ids=bucket_ids,
            features=features,
            source_types=source_types,
            document_ids=document_ids,
            source_paths=source_paths,
            allowed_source_paths=allowed_source_paths,
            max_sources_per_title=max_sources_per_title,
            max_sources_per_source_type=max_sources_per_source_type,
            max_sources_per_source_path=max_sources_per_source_path,
        )
        targeted_sources = additional_sources or []
        sources = _merge_sources(targeted_sources, search.sources)
        selected_top_k = top_k or self._default_top_k
        sources = sources[:selected_top_k]
        context_policy = _build_context_policy(search.query_hints)
        prompt_sources = _apply_context_policy(
            sources,
            context_policy=context_policy,
        )
        extra_prompt_rules = _build_extra_prompt_rules(search.query_hints)
        prompt = build_rag_prompt(
            question=message,
            sources=prompt_sources,
            extra_rules=extra_prompt_rules,
            memory_context=memory_context,
        )
        result = await self._ollama_client.generate(
            model=selected_model,
            prompt=prompt,
            keep_alive=self._generation_keep_alive,
            options={
                "temperature": self._generation_temperature,
                "top_p": self._generation_top_p,
            },
            think=False,
        )

        latency_ms = int((perf_counter() - started_at) * 1000)
        diversity = {
            "max_sources_per_title": max_sources_per_title if max_sources_per_title is not None else 1,
            "max_sources_per_source_type": max_sources_per_source_type,
            "max_sources_per_source_path": max_sources_per_source_path,
        }
        retrieval = {
            **search.retrieval,
            "additional_source_count": len(targeted_sources),
            "additional_source_ids": [source.id for source in targeted_sources],
            "final_top_k": len(sources),
        }

        return RagChatResponse(
            model=selected_model,
            response=result.get("response", ""),
            latency_ms=latency_ms,
            collection=self._qdrant_store.collection_name,
            sources=sources,
            score_threshold=search.score_threshold,
            features=search.features,
            source_types=search.source_types,
            diversity=diversity,
            retrieval=retrieval,
            query_hints=search.query_hints,
            context_policy=context_policy,
            prompt_tokens_estimate=_estimate_tokens(prompt),
        )

    def _retrieve_sources(
        self,
        *,
        query_vector: list[float],
        message: str,
        candidate_k: int,
        selected_top_k: int,
        selected_score_threshold: float | None,
        selected_tenant_id: str | None,
        selected_bucket_ids: list[str],
        selected_features: list[str],
        selected_source_types: list[str],
        selected_document_ids: list[str],
        selected_source_paths: list[str],
        selected_allowed_source_paths: list[str],
        routing_hints: dict[str, object],
    ) -> tuple[list[SourceChunk], list[str], int, int]:
        sources = self._qdrant_store.search(
            query_vector=query_vector,
            limit=candidate_k,
            tenant_id=selected_tenant_id,
            bucket_ids=selected_bucket_ids,
            features=selected_features,
            source_types=selected_source_types,
            document_ids=selected_document_ids,
            source_paths=selected_source_paths,
            allowed_source_paths=selected_allowed_source_paths,
        )
        sources = _filter_sources_by_score(sources, selected_score_threshold)
        docx_supplement_sources = self._supplement_docx_sources(
            sources=sources,
            message=message,
            selected_tenant_id=selected_tenant_id,
            selected_bucket_ids=selected_bucket_ids,
            selected_source_types=selected_source_types,
            selected_document_ids=selected_document_ids,
            selected_source_paths=selected_source_paths,
            selected_allowed_source_paths=selected_allowed_source_paths,
            limit=selected_top_k,
        )
        sources = _merge_sources(docx_supplement_sources, sources)
        excel_supplement_sources = self._supplement_excel_sources(
            message=message,
            selected_tenant_id=selected_tenant_id,
            selected_bucket_ids=selected_bucket_ids,
            selected_source_types=selected_source_types,
            selected_document_ids=selected_document_ids,
            selected_source_paths=selected_source_paths,
            selected_allowed_source_paths=selected_allowed_source_paths,
            limit=selected_top_k,
        )
        sources = _merge_sources(excel_supplement_sources, sources)
        excel_visual_supplement_sources = self._supplement_excel_visual_sources(
            message=message,
            selected_tenant_id=selected_tenant_id,
            selected_bucket_ids=selected_bucket_ids,
            selected_source_types=selected_source_types,
            selected_document_ids=selected_document_ids,
            selected_source_paths=selected_source_paths,
            selected_allowed_source_paths=selected_allowed_source_paths,
            limit=selected_top_k,
        )
        sources = _merge_sources(excel_visual_supplement_sources, sources)
        sources = _rerank_docx_sources(sources, message)
        required_source_types = _required_source_types_for_supplement(
            routing_hints=routing_hints,
            selected_source_types=selected_source_types,
            selected_bucket_ids=selected_bucket_ids,
            selected_document_ids=selected_document_ids,
            selected_source_paths=selected_source_paths,
        )
        sources = self._supplement_required_source_types(
            sources=sources,
            query_vector=query_vector,
            selected_tenant_id=selected_tenant_id,
            selected_bucket_ids=selected_bucket_ids,
            selected_features=selected_features,
            selected_document_ids=selected_document_ids,
            selected_source_paths=selected_source_paths,
            selected_allowed_source_paths=selected_allowed_source_paths,
            required_source_types=required_source_types,
            limit=selected_top_k,
        )
        return (
            sources,
            required_source_types,
            len(excel_supplement_sources) + len(excel_visual_supplement_sources),
            len(docx_supplement_sources),
        )

    def _supplement_required_source_types(
        self,
        *,
        sources: list[SourceChunk],
        query_vector: list[float],
        selected_tenant_id: str | None,
        selected_bucket_ids: list[str],
        selected_features: list[str],
        selected_document_ids: list[str],
        selected_source_paths: list[str],
        selected_allowed_source_paths: list[str],
        required_source_types: list[str],
        limit: int,
    ) -> list[SourceChunk]:
        supplemented_sources = sources
        for required_source_type in required_source_types:
            if _contains_source_type(supplemented_sources[:limit], required_source_type):
                continue
            supplemental_sources = self._qdrant_store.search(
                query_vector=query_vector,
                limit=limit,
                tenant_id=selected_tenant_id,
                bucket_ids=selected_bucket_ids,
                features=selected_features,
                source_types=[required_source_type],
                document_ids=selected_document_ids,
                source_paths=selected_source_paths,
                allowed_source_paths=selected_allowed_source_paths,
            )
            supplemented_sources = _merge_sources(
                supplemental_sources[:2],
                supplemented_sources,
            )
        return supplemented_sources

    def _supplement_excel_sources(
        self,
        *,
        message: str,
        selected_tenant_id: str | None,
        selected_bucket_ids: list[str],
        selected_source_types: list[str],
        selected_document_ids: list[str],
        selected_source_paths: list[str],
        selected_allowed_source_paths: list[str],
        limit: int,
    ) -> list[SourceChunk]:
        if selected_source_types and "excel_row" not in selected_source_types:
            return []
        if (
            not selected_bucket_ids
            and not selected_document_ids
            and not selected_source_paths
            and not selected_allowed_source_paths
        ):
            return []

        candidates = self._qdrant_store.scroll(
            limit=self._excel_supplement_scroll_limit,
            tenant_id=selected_tenant_id,
            bucket_ids=selected_bucket_ids,
            source_types=["excel_row"],
            document_ids=selected_document_ids,
            source_paths=selected_source_paths,
            allowed_source_paths=selected_allowed_source_paths,
        )
        if not candidates:
            return []

        exact_terms = _extract_excel_exact_terms(message)
        exact_matches = [
            source
            for source in candidates
            if exact_terms and _excel_exact_match_count(source, exact_terms) > 0
        ]
        exact_matches = sorted(
            exact_matches,
            key=lambda source: (
                -_excel_exact_match_count(source, exact_terms),
                _excel_row_number(source),
            ),
        )

        header_matches: list[SourceChunk] = []
        if _looks_like_document_header_question(message):
            header_matches = [
                source
                for source in candidates
                if _excel_row_number(source) <= 12
            ]
            header_matches = sorted(header_matches, key=_excel_row_number)

        return _merge_sources(exact_matches[:limit], header_matches[:limit])

    def _supplement_excel_visual_sources(
        self,
        *,
        message: str,
        selected_tenant_id: str | None,
        selected_bucket_ids: list[str],
        selected_source_types: list[str],
        selected_document_ids: list[str],
        selected_source_paths: list[str],
        selected_allowed_source_paths: list[str],
        limit: int,
    ) -> list[SourceChunk]:
        if selected_source_types and "image_digest" not in selected_source_types:
            return []
        if (
            not selected_bucket_ids
            and not selected_document_ids
            and not selected_source_paths
            and not selected_allowed_source_paths
        ):
            return []

        candidates = self._qdrant_store.scroll(
            limit=self._excel_supplement_scroll_limit,
            tenant_id=selected_tenant_id,
            bucket_ids=selected_bucket_ids,
            source_types=["image_digest"],
            document_ids=selected_document_ids,
            source_paths=selected_source_paths,
            allowed_source_paths=selected_allowed_source_paths,
        )
        if not candidates:
            return []

        exact_terms = _extract_excel_exact_terms(message)
        exact_matches = [
            source
            for source in candidates
            if _is_xlsx_anchor_image_source(source)
            and exact_terms
            and _excel_exact_match_count(source, exact_terms) > 0
        ]
        exact_matches = sorted(
            exact_matches,
            key=lambda source: (
                -_excel_exact_match_count(source, exact_terms),
                _excel_anchor_row_number(source),
                _excel_embedded_image_index(source),
            ),
        )
        return exact_matches[:limit]

    def _supplement_docx_sources(
        self,
        *,
        sources: list[SourceChunk],
        message: str,
        selected_tenant_id: str | None,
        selected_bucket_ids: list[str],
        selected_source_types: list[str],
        selected_document_ids: list[str],
        selected_source_paths: list[str],
        selected_allowed_source_paths: list[str],
        limit: int,
    ) -> list[SourceChunk]:
        if selected_source_types and "docx" not in selected_source_types:
            return []
        if (
            not selected_bucket_ids
            and not selected_document_ids
            and not selected_source_paths
            and not selected_allowed_source_paths
        ):
            return []

        candidates = self._qdrant_store.scroll(
            limit=self._docx_supplement_scroll_limit,
            tenant_id=selected_tenant_id,
            bucket_ids=selected_bucket_ids,
            source_types=["docx"],
            document_ids=selected_document_ids,
            source_paths=selected_source_paths,
            allowed_source_paths=selected_allowed_source_paths,
        )
        if not candidates:
            return []

        exact_terms = _extract_docx_exact_terms(message)
        exact_matches = [
            source
            for source in candidates
            if exact_terms and _docx_exact_match_count(source, exact_terms) > 0
        ]
        exact_matches = sorted(
            exact_matches,
            key=lambda source: (
                -_docx_exact_match_count(source, exact_terms),
                _docx_sort_key(source),
            ),
        )

        neighbor_matches = _docx_neighbor_sources(
            seed_sources=_merge_sources(sources, exact_matches[:limit]),
            candidates=candidates,
            radius=2,
        )
        return _merge_sources(exact_matches[:limit], neighbor_matches[:limit])


def build_rag_prompt(
    question: str,
    sources: list[SourceChunk],
    extra_rules: list[str] | None = None,
    memory_context: dict[str, object] | None = None,
) -> str:
    context_blocks = []
    for index, source in enumerate(sources, start=1):
        title = source.title or "Untitled source"
        source_type = source.source_type or "unknown"
        features = ", ".join(source.feature) if source.feature else "unknown"
        file_name = _source_file_name(source)
        context_blocks.append(
            "\n".join(
                [
                    (
                        f"[Источник {index}: {source_type} | title={title} | "
                        f"file={file_name} | feature={features}]"
                    ),
                    source.content.strip(),
                ]
            )
        )

    context = "\n\n".join(context_blocks) if context_blocks else "Контекст не найден."
    memory_text = _build_memory_prompt_text(memory_context)
    memory_rules = [
        (
            "Память диалога помогает учитывать предыдущие цели и формулировки "
            "пользователя, но не является источником фактов и не отменяет "
            "актуальный блок Контекст."
        ),
        (
            "Факты из пользовательских документов, метрики, причины инцидентов "
            "и рекомендации бери только из блока Контекст."
        ),
    ] if memory_text else []
    dynamic_rules = "\n".join(
        f"- {rule}"
        for rule in [*memory_rules, *(extra_rules or [])]
    )
    rules = "\n".join(
        [
            "- Отвечай на русском языке.",
            "- Пиши кратко и по делу: обычно 3–6 предложений или короткий список.",
            "- Не пиши длинные эссе, вступления и повторения.",
            "- Не выдумывай факты, которых нет в контексте.",
            (
                "- Если в контексте есть релевантный фрагмент, ответь по нему, "
                "даже если документ не относится к продукту TaskFlow AI."
            ),
            (
                "- Если header источника содержит `file=<имя файла>`, считай этот фрагмент "
                "частью указанного файла. Не говори, что файл отсутствует, если "
                "в Контексте есть фрагмент с таким `file`."
            ),
            (
                "- Если пользователь спрашивает про конкретный файл по имени, а в Контексте "
                "нет источника с таким же `file=...`, ответь только что этого файла нет "
                "в доступном контексте. На этом остановись: не описывай, не сравнивай и "
                "не упоминай другие файлы, изображения или документы из Контекста."
            ),
            (
                "- Если источник выглядит как шутка, заметка или черновик, "
                "можно указать это как оговорку, но не отказывайся отвечать "
                "только из-за типа источника."
            ),
            "- Если в контексте нет ответа, скажи, каких данных не хватает.",
            "- Сначала факты, потом короткая интерпретация только если она нужна.",
            "- Если используешь числа, бери их только из контекста.",
            (
                "- Не перечисляй источники, файлы, CHUNK, номера фрагментов, UUID "
                "и служебные metadata в ответе. Пиши только содержание ответа."
            ),
            dynamic_rules,
        ]
    ).strip()

    return f"""Ты — AI-ассистент для Product Owner, который отвечает по пользовательским документам.

Твоя задача: дать короткий grounded-ответ на вопрос пользователя строго на основе предоставленного контекста.

Правила:
{rules}

Контекст:

{context}

Память диалога:

{memory_text or "Память диалога не используется."}

Вопрос пользователя:
{question}
"""


def _build_memory_prompt_text(memory_context: dict[str, object] | None) -> str:
    if not memory_context or memory_context.get("used") is not True:
        return ""
    content = str(memory_context.get("content") or "").strip()
    return content


def _source_file_name(source: SourceChunk) -> str:
    document_metadata = source.metadata.get("document_metadata") or {}
    if isinstance(document_metadata, dict):
        for key in ("document_file_name", "file_name"):
            value = document_metadata.get(key)
            if value:
                return str(value)
    if source.source_path:
        return _display_file_name(source.source_path.rsplit("/", maxsplit=1)[-1])
    return "unknown"


def _display_file_name(file_name: str) -> str:
    # Storage paths look like `<uuid>_<original_name>`; prefer the original name in prompts.
    if len(file_name) > 37 and file_name[36] == "_":
        prefix = file_name[:36]
        if all(char in "0123456789abcdefABCDEF-" for char in prefix):
            return file_name[37:] or file_name
    return file_name


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _build_context_policy(query_hints: dict[str, object]) -> dict[str, object]:
    return {
        "numeric_line_sanitization": query_hints.get("metric_negative_marker") is True,
    }


def _apply_context_policy(
    sources: list[SourceChunk],
    *,
    context_policy: dict[str, object],
) -> list[SourceChunk]:
    if context_policy.get("numeric_line_sanitization") is not True:
        return sources

    return [
        source.model_copy(
            update={
                "title": _sanitize_metric_title(source.title),
                "content": _remove_numeric_metric_lines(source.content),
            }
        )
        for source in sources
    ]


def _build_extra_prompt_rules(query_hints: dict[str, object]) -> list[str]:
    if query_hints.get("metric_negative_marker") is True:
        return [
            (
                "Пользователь попросил не использовать метрики. "
                "Не упоминай числовые KPI, проценты, счетчики тикетов, adoption, "
                "latency/delay metrics и не давай рекомендации про метрики. "
                "Отвечай качественно, без числовых метрик."
            )
        ]
    return []


def _remove_numeric_metric_lines(text: str) -> str:
    kept_lines = [
        line
        for line in text.splitlines()
        if not _looks_like_numeric_metric_line(line)
    ]
    sanitized = "\n".join(kept_lines).strip()
    return sanitized or "Контент источника скрыт из-за ограничения пользователя не использовать метрики."


def _sanitize_metric_title(title: str | None) -> str | None:
    if title is None:
        return None
    if _looks_like_numeric_metric_line(title):
        # TODO: hide sanitized titles from prompt metadata instead of replacing them.
        return "Источник без числовых метрик"
    return title


def _looks_like_numeric_metric_line(line: str) -> bool:
    normalized = line.strip().lower()
    if not normalized:
        return False

    if "%" in normalized:
        return True

    numeric_metric_markers = (
        "metric",
        "метрик",
        "kpi",
        "adoption",
        "tickets",
        "тикет",
        "support tickets",
        "latency",
        "delay",
        "задержк",
        "минут",
        "ms",
        "мс",
    )
    has_number = re.search(r"\d", normalized) is not None
    has_metric_marker = any(marker in normalized for marker in numeric_metric_markers)
    return has_number and has_metric_marker


def _filter_sources_by_score(
    sources: list[SourceChunk],
    score_threshold: float | None,
) -> list[SourceChunk]:
    if score_threshold is None:
        return sources
    return [
        source
        for source in sources
        if source.score is not None and source.score >= score_threshold
    ]


def _is_narrow_document_scope(
    *,
    bucket_ids: list[str],
    document_ids: list[str],
    source_paths: list[str],
) -> bool:
    return 0 < len(bucket_ids) + len(document_ids) + len(source_paths) <= 3


def _lower_score_threshold(current: float | None, target: float) -> float:
    if current is None:
        return target
    return min(current, target)


def _contains_source_type(sources: list[SourceChunk], source_type: str) -> bool:
    normalized_source_type = source_type.strip().lower()
    return any(
        (source.source_type or "").strip().lower() == normalized_source_type
        for source in sources
    )


def _required_source_types_for_supplement(
    *,
    routing_hints: dict[str, object],
    selected_source_types: list[str],
    selected_bucket_ids: list[str],
    selected_document_ids: list[str],
    selected_source_paths: list[str],
) -> list[str]:
    required_source_types = _normalize_values(
        routing_hints.get("required_source_types") or []
    )
    has_retrieval_scope = bool(
        selected_bucket_ids or selected_document_ids or selected_source_paths
    )
    if has_retrieval_scope and len(selected_source_types) > 1:
        required_source_types = _merge_values(required_source_types, selected_source_types)
    return required_source_types


def _merge_values(left: list[str], right: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for value in [*left, *right]:
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _extract_exact_numeric_terms(text: str) -> list[str]:
    return re.findall(r"\b\d{6,}\b", text)


def _extract_excel_exact_terms(text: str) -> list[str]:
    raw_terms = re.findall(
        r"[A-Za-zА-Яа-яЁё_#][A-Za-zА-Яа-яЁё0-9_#.-]{2,}|\b\d+(?:[,.]\d+)?\b",
        text,
    )
    skipped_terms = {
        "xls",
        "xlsx",
        "excel",
        "hard_for_analis",
        "известно",
        "город",
        "срок",
        "годности",
        "объем",
        "объём",
        "цену",
        "цена",
        "кегу",
        "какой",
        "какая",
        "какие",
        "какую",
        "что",
        "про",
        "написано",
        "изображено",
        "картинке",
        "картинка",
        "продукта",
        "продукт",
        "указано",
        "алкоголь",
        "плотность",
    }
    terms: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        normalized = term.strip(".,:;()[]{}").lower()
        if not normalized or normalized in skipped_terms:
            continue
        is_numeric = _is_excel_numeric_term(normalized)
        if is_numeric and len(re.sub(r"\D", "", normalized)) < 2:
            continue
        if not is_numeric and len(normalized) < 4:
            continue
        if normalized in seen:
            continue
        terms.append(normalized)
        seen.add(normalized)
    return terms


def _is_excel_numeric_term(term: str) -> bool:
    return re.fullmatch(r"\d+(?:[,.]\d+)?", term) is not None


def _excel_exact_match_count(source: SourceChunk, terms: list[str]) -> int:
    body = source.content.lower()
    return sum(1 for term in terms if _excel_term_in_body(term, body))


def _excel_term_in_body(term: str, body: str) -> bool:
    if term in body:
        return True
    if "," in term:
        return term.replace(",", ".") in body
    if "." in term:
        return term.replace(".", ",") in body
    return False


def _looks_like_document_header_question(text: str) -> bool:
    normalized = text.lower()
    markers = (
        "организац",
        "дата",
        "документ",
        "реквизит",
        "компан",
        "company",
        "document",
    )
    return any(marker in normalized for marker in markers)


def _excel_row_number(source: SourceChunk) -> int:
    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        return int(document_metadata.get("excel_row_number") or 0)
    except (TypeError, ValueError):
        return 0


def _is_xlsx_anchor_image_source(source: SourceChunk) -> bool:
    document_metadata = source.metadata.get("document_metadata") or {}
    return (
        source.source_type == "image_digest"
        and document_metadata.get("parent_source_type") == "xlsx"
        and document_metadata.get("anchor_type") == "xlsx_cell"
    )


def _excel_anchor_row_number(source: SourceChunk) -> int:
    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        return int(document_metadata.get("anchor_row") or 0)
    except (TypeError, ValueError):
        return 0


def _excel_embedded_image_index(source: SourceChunk) -> int:
    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        return int(document_metadata.get("embedded_image_index") or 0)
    except (TypeError, ValueError):
        return 0


def _extract_docx_exact_terms(text: str) -> list[str]:
    raw_terms = re.findall(r"[A-Za-zА-Яа-я_#][A-Za-zА-Яа-я0-9_#.-]{2,}|\b\d{2,}\b", text)
    skipped_terms = {"docx", "document", "документ"}
    terms: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        normalized = term.strip(".,:;()[]{}").lower()
        if not normalized or normalized in skipped_terms:
            continue
        has_latin_or_number = re.search(r"[a-z0-9#]", normalized) is not None
        if not has_latin_or_number:
            continue
        if normalized in seen:
            continue
        terms.append(normalized)
        seen.add(normalized)
    return terms


def _docx_exact_match_count(source: SourceChunk, terms: list[str]) -> int:
    body = _docx_searchable_body(source).lower()
    return sum(1 for term in terms if term in body)


def _docx_searchable_body(source: SourceChunk) -> str:
    skipped_prefixes = ("file:",)
    return "\n".join(
        line
        for line in source.content.splitlines()
        if not line.strip().lower().startswith(skipped_prefixes)
    )


def _docx_neighbor_sources(
    *,
    seed_sources: list[SourceChunk],
    candidates: list[SourceChunk],
    radius: int,
) -> list[SourceChunk]:
    seed_indexes = [
        index
        for source in seed_sources
        if (index := _docx_paragraph_index(source)) is not None
    ]
    if not seed_indexes:
        return []

    neighbors = [
        candidate
        for candidate in candidates
        if _docx_is_neighbor(candidate, seed_indexes=seed_indexes, radius=radius)
    ]
    return sorted(neighbors, key=_docx_sort_key)


def _docx_is_neighbor(
    source: SourceChunk,
    *,
    seed_indexes: list[int],
    radius: int,
) -> bool:
    paragraph_index = _docx_paragraph_index(source)
    if paragraph_index is not None:
        return any(abs(paragraph_index - seed_index) <= radius for seed_index in seed_indexes)

    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        start_index = int(document_metadata.get("paragraph_start_index"))
        end_index = int(document_metadata.get("paragraph_end_index"))
    except (TypeError, ValueError):
        return False
    return any(start_index - radius <= seed_index <= end_index + radius for seed_index in seed_indexes)


def _docx_paragraph_index(source: SourceChunk) -> int | None:
    document_metadata = source.metadata.get("document_metadata") or {}
    try:
        return int(document_metadata.get("paragraph_index"))
    except (TypeError, ValueError):
        return None


def _docx_sort_key(source: SourceChunk) -> tuple[str, int, int, str]:
    document_metadata = source.metadata.get("document_metadata") or {}
    source_path = source.source_path or ""
    block_type = str(document_metadata.get("block_type") or "")
    paragraph_index = _docx_paragraph_index(source)
    if paragraph_index is None:
        try:
            paragraph_index = int(document_metadata.get("paragraph_start_index") or 0)
        except (TypeError, ValueError):
            paragraph_index = 0
    block_priority = 0 if block_type == "paragraph" else 1
    return source_path, paragraph_index, block_priority, source.id


def _rerank_docx_sources(sources: list[SourceChunk], message: str) -> list[SourceChunk]:
    if not any(source.source_type == "docx" for source in sources):
        return sources

    exact_terms = _extract_docx_exact_terms(message)
    ranked = [
        (index, source, _docx_rerank_score(source, exact_terms))
        for index, source in enumerate(sources)
    ]
    ranked = sorted(ranked, key=lambda item: (-item[2], item[0]))
    return [source for _, source, _ in ranked]


def _docx_rerank_score(source: SourceChunk, exact_terms: list[str]) -> float:
    if source.source_type != "docx":
        return source.score or 0.0

    document_metadata = source.metadata.get("document_metadata") or {}
    block_type = document_metadata.get("block_type")
    base_score = source.score if source.score is not None else 0.75
    exact_boost = min(0.2, _docx_exact_match_count(source, exact_terms) * 0.05)
    block_boost = 0.03 if block_type == "paragraph_window" else 0.0
    return base_score + exact_boost + block_boost


def _merge_sources(
    preferred_sources: list[SourceChunk],
    fallback_sources: list[SourceChunk],
) -> list[SourceChunk]:
    merged: list[SourceChunk] = []
    seen_ids: set[str] = set()
    for source in [*preferred_sources, *fallback_sources]:
        if source.id in seen_ids:
            continue
        merged.append(source)
        seen_ids.add(source.id)
    return merged


def _normalize_features(features: list[str]) -> list[str]:
    return _normalize_values(features)


def _normalize_values(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()]


def _apply_source_diversity(
    sources: list[SourceChunk],
    *,
    max_sources_per_title: int | None,
    max_sources_per_source_type: int | None,
    max_sources_per_source_path: int | None,
) -> list[SourceChunk]:
    kept: list[SourceChunk] = []
    title_counts: dict[str, int] = {}
    source_type_counts: dict[str, int] = {}
    source_path_counts: dict[str, int] = {}

    for source in sources:
        title_key = (source.title or "").strip().lower()
        source_type_key = (source.source_type or "").strip().lower()
        source_path_key = (source.source_path or "").strip().lower()

        if _exceeds_limit(title_counts, title_key, max_sources_per_title):
            continue
        if _exceeds_limit(source_type_counts, source_type_key, max_sources_per_source_type):
            continue
        if _exceeds_limit(source_path_counts, source_path_key, max_sources_per_source_path):
            continue

        kept.append(source)
        _increment_count(title_counts, title_key)
        _increment_count(source_type_counts, source_type_key)
        _increment_count(source_path_counts, source_path_key)

    return kept


def _exceeds_limit(counts: dict[str, int], key: str, limit: int | None) -> bool:
    if limit is None or not key:
        return False
    return counts.get(key, 0) >= limit


def _increment_count(counts: dict[str, int], key: str) -> None:
    if not key:
        return
    counts[key] = counts.get(key, 0) + 1

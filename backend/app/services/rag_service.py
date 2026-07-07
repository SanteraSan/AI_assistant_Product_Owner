import re
from time import perf_counter

from app.clients.qdrant_store import QdrantStore
from app.models.chat import RagChatResponse, SourceChunk
from app.services.feature_extractor import FeatureExtractor
from app.services.ollama_client import OllamaClient
from app.services.query_router import QueryRouter


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
    ) -> None:
        self._ollama_client = ollama_client
        self._qdrant_store = qdrant_store
        self._feature_extractor = feature_extractor
        self._query_router = query_router
        self._embedding_model = embedding_model
        self._default_model = default_model
        self._default_top_k = default_top_k
        self._default_score_threshold = default_score_threshold

    async def answer(
        self,
        message: str,
        model: str | None = None,
        retrieval_query: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
        features: list[str] | None = None,
        source_types: list[str] | None = None,
        max_sources_per_title: int | None = None,
        max_sources_per_source_type: int | None = None,
        max_sources_per_source_path: int | None = None,
    ) -> RagChatResponse:
        selected_model = model or self._default_model
        selected_top_k = top_k or self._default_top_k
        selected_retrieval_query = retrieval_query or message
        selected_score_threshold = (
            score_threshold if score_threshold is not None else self._default_score_threshold
        )
        candidate_k = selected_top_k * 3
        selected_features = _normalize_features(features or [])
        if not selected_features:
            selected_features = self._feature_extractor.extract(selected_retrieval_query)
        selected_source_types = _normalize_values(source_types or [])
        routing_decision = self._query_router.route(
            message=selected_retrieval_query,
            source_types=selected_source_types,
            score_threshold=selected_score_threshold,
            user_provided_source_types=bool(source_types),
            user_provided_score_threshold=score_threshold is not None,
        )
        selected_source_types = routing_decision.source_types
        selected_score_threshold = routing_decision.score_threshold
        started_at = perf_counter()

        query_vector = await self._ollama_client.embed(
            self._embedding_model,
            selected_retrieval_query,
        )
        sources = self._qdrant_store.search(
            query_vector=query_vector,
            limit=candidate_k,
            features=selected_features,
            source_types=selected_source_types,
        )
        sources = _filter_sources_by_score(sources, selected_score_threshold)
        required_source_types = _normalize_values(
            routing_decision.hints.get("required_source_types") or []
        )
        sources = self._supplement_required_source_types(
            sources=sources,
            query_vector=query_vector,
            selected_features=selected_features,
            required_source_types=required_source_types,
            limit=selected_top_k,
        )
        diversity = {
            "max_sources_per_title": max_sources_per_title if max_sources_per_title is not None else 1,
            "max_sources_per_source_type": max_sources_per_source_type,
            "max_sources_per_source_path": max_sources_per_source_path,
        }
        sources = _apply_source_diversity(
            sources,
            max_sources_per_title=diversity["max_sources_per_title"],
            max_sources_per_source_type=diversity["max_sources_per_source_type"],
            max_sources_per_source_path=diversity["max_sources_per_source_path"],
        )
        sources = sources[:selected_top_k]
        context_policy = _build_context_policy(routing_decision.hints)
        prompt_sources = _apply_context_policy(
            sources,
            context_policy=context_policy,
        )
        extra_prompt_rules = _build_extra_prompt_rules(routing_decision.hints)
        prompt = build_rag_prompt(
            question=message,
            sources=prompt_sources,
            extra_rules=extra_prompt_rules,
        )
        result = await self._ollama_client.generate(
            model=selected_model,
            prompt=prompt,
            keep_alive="10m",
            options={"temperature": 0.1, "top_p": 0.9},
            think=False,
        )

        latency_ms = int((perf_counter() - started_at) * 1000)

        return RagChatResponse(
            model=selected_model,
            response=result.get("response", ""),
            latency_ms=latency_ms,
            collection=self._qdrant_store.collection_name,
            sources=sources,
            score_threshold=selected_score_threshold,
            features=selected_features,
            source_types=selected_source_types,
            diversity=diversity,
            retrieval={
                "requested_top_k": selected_top_k,
                "candidate_k": candidate_k,
                "retrieval_query": selected_retrieval_query,
                "required_source_types": required_source_types,
                "final_top_k": len(sources),
            },
            query_hints=routing_decision.hints,
            context_policy=context_policy,
            prompt_tokens_estimate=_estimate_tokens(prompt),
        )

    def _supplement_required_source_types(
        self,
        *,
        sources: list[SourceChunk],
        query_vector: list[float],
        selected_features: list[str],
        required_source_types: list[str],
        limit: int,
    ) -> list[SourceChunk]:
        supplemented_sources = sources
        for required_source_type in required_source_types:
            if _contains_source_type(supplemented_sources, required_source_type):
                continue
            supplemental_sources = self._qdrant_store.search(
                query_vector=query_vector,
                limit=limit,
                features=selected_features,
                source_types=[required_source_type],
            )
            supplemented_sources = _merge_sources(
                supplemental_sources[:2],
                supplemented_sources,
            )
        return supplemented_sources


def build_rag_prompt(
    question: str,
    sources: list[SourceChunk],
    extra_rules: list[str] | None = None,
) -> str:
    context_blocks = []
    for index, source in enumerate(sources, start=1):
        title = source.title or "Untitled source"
        source_type = source.source_type or "unknown"
        features = ", ".join(source.feature) if source.feature else "unknown"
        context_blocks.append(
            "\n".join(
                [
                    f"[CHUNK {index}: {source_type} | title={title} | feature={features}]",
                    source.content.strip(),
                ]
            )
        )

    context = "\n\n".join(context_blocks) if context_blocks else "Контекст не найден."
    dynamic_rules = "\n".join(
        f"- {rule}"
        for rule in (extra_rules or [])
    )
    rules = "\n".join(
        [
            "- Отвечай на русском языке.",
            "- Не выдумывай факты, которых нет в контексте.",
            "- Если в контексте нет ответа, скажи, каких данных не хватает.",
            "- Отделяй факты из контекста от интерпретации и рекомендации.",
            "- Если используешь числа, бери их только из контекста.",
            "- В конце перечисли источники, которые реально использовал.",
            dynamic_rules,
        ]
    ).strip()

    return f"""Ты — AI-ассистент для Product Owner в B2B SaaS продукте TaskFlow AI.

Твоя задача: ответить на вопрос пользователя строго на основе предоставленного контекста.

Правила:
{rules}

Контекст:

{context}

Вопрос пользователя:
{question}
"""


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


def _contains_source_type(sources: list[SourceChunk], source_type: str) -> bool:
    normalized_source_type = source_type.strip().lower()
    return any(
        (source.source_type or "").strip().lower() == normalized_source_type
        for source in sources
    )


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

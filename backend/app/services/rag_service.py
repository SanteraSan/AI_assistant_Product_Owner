from dataclasses import dataclass
from time import perf_counter

from app.clients.qdrant_store import QdrantStore
from app.models.chat import RagChatResponse, SourceChunk
from app.services.external_scope import (
    decide_external_scope,
    sources_include_non_synthetic,
)
from app.services.feature_extractor import FeatureExtractor
from app.services.hh_resume_sections import prefer_named_resume_employer
from app.services.llm.gateway import ModelGateway
from app.services.ollama_client import OllamaClient
from app.services.query_router import QueryRouter
from app.services.rag_docx import _rerank_docx_sources, supplement_docx_sources
from app.services.rag_excel import supplement_excel_sources, supplement_excel_visual_sources
from app.services.rag_prompt import (
    _apply_context_policy,
    _build_context_policy,
    _build_extra_prompt_rules,
    _estimate_tokens,
    build_rag_prompt,
)


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
        model_gateway: ModelGateway | None = None,
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
        self._model_gateway = model_gateway

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
        sources = prefer_named_resume_employer(query, sources)
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
        approach: str | None = None,
        session_seen_non_synthetic: bool = False,
        provider_api_key: str | None = None,
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
        retrieved_non_synthetic = sources_include_non_synthetic(sources)
        scope_decision = decide_external_scope(
            approach=approach,
            endpoint="rag",
            session_seen_non_synthetic_flag=session_seen_non_synthetic,
            retrieved_non_synthetic=retrieved_non_synthetic,
        )
        generation_options = {
            "temperature": self._generation_temperature,
            "top_p": self._generation_top_p,
        }
        if self._model_gateway is not None:
            generation = await self._model_gateway.generate(
                model=selected_model,
                prompt=prompt,
                approach=approach,
                endpoint="rag",
                allow_external_fallback=scope_decision.allow_external_fallback,
                keep_alive=self._generation_keep_alive,
                options=generation_options,
                think=False,
                provider_api_key=provider_api_key,
            )
            response_text = generation.response
            provider = generation.provider
            provider_response_model_id = generation.provider_response_model_id
            fallback_from = generation.fallback_from
            fallback_to = generation.fallback_to
            finish_reason = generation.finish_reason
            prompt_tokens = generation.prompt_tokens
            completion_tokens = generation.completion_tokens
            cost_estimated = generation.cost_estimated
            estimated_cost_usd = generation.estimated_cost_usd
        else:
            result = await self._ollama_client.generate(
                model=selected_model,
                prompt=prompt,
                keep_alive=self._generation_keep_alive,
                options=generation_options,
                think=False,
            )
            response_text = str(result.get("response") or "")
            provider = "ollama"
            provider_response_model_id = str(result.get("model") or selected_model)
            fallback_from = None
            fallback_to = None
            finish_reason = "stop"
            prompt_tokens = None
            completion_tokens = None
            cost_estimated = True
            estimated_cost_usd = None

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
            "external_scope": {
                "allow_external_fallback": scope_decision.allow_external_fallback,
                "persist_session_seen_non_synthetic": (
                    scope_decision.persist_session_seen_non_synthetic
                ),
                "deny_reason": scope_decision.deny_reason,
            },
        }

        return RagChatResponse(
            model=selected_model,
            response=response_text,
            latency_ms=latency_ms,
            provider=provider,
            provider_response_model_id=provider_response_model_id,
            fallback_from=fallback_from,
            fallback_to=fallback_to,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_estimated=cost_estimated,
            estimated_cost_usd=estimated_cost_usd,
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
        docx_supplement_sources = supplement_docx_sources(
            qdrant_store=self._qdrant_store,
            scroll_limit=self._docx_supplement_scroll_limit,
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
        excel_supplement_sources = supplement_excel_sources(
            qdrant_store=self._qdrant_store,
            scroll_limit=self._excel_supplement_scroll_limit,
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
        excel_visual_supplement_sources = supplement_excel_visual_sources(
            qdrant_store=self._qdrant_store,
            scroll_limit=self._excel_supplement_scroll_limit,
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

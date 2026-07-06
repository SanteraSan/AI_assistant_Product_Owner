from time import perf_counter

from app.clients.qdrant_store import QdrantStore
from app.models.chat import RagChatResponse, SourceChunk
from app.services.feature_extractor import FeatureExtractor
from app.services.ollama_client import OllamaClient


class RagService:
    def __init__(
        self,
        *,
        ollama_client: OllamaClient,
        qdrant_store: QdrantStore,
        feature_extractor: FeatureExtractor,
        embedding_model: str,
        default_model: str,
        default_top_k: int,
        default_score_threshold: float | None,
    ) -> None:
        self._ollama_client = ollama_client
        self._qdrant_store = qdrant_store
        self._feature_extractor = feature_extractor
        self._embedding_model = embedding_model
        self._default_model = default_model
        self._default_top_k = default_top_k
        self._default_score_threshold = default_score_threshold

    async def answer(
        self,
        message: str,
        model: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
        features: list[str] | None = None,
    ) -> RagChatResponse:
        selected_model = model or self._default_model
        selected_top_k = top_k or self._default_top_k
        selected_score_threshold = (
            score_threshold if score_threshold is not None else self._default_score_threshold
        )
        selected_features = _normalize_features(features or [])
        if not selected_features:
            selected_features = self._feature_extractor.extract(message)
        started_at = perf_counter()

        query_vector = await self._ollama_client.embed(self._embedding_model, message)
        sources = self._qdrant_store.search(
            query_vector=query_vector,
            limit=selected_top_k,
            features=selected_features,
        )
        sources = _filter_sources_by_score(sources, selected_score_threshold)
        prompt = build_rag_prompt(question=message, sources=sources)
        result = await self._ollama_client.generate(
            model=selected_model,
            prompt=prompt,
            keep_alive="10m",
            options={"temperature": 0.1, "top_p": 0.9},
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
            prompt_tokens_estimate=_estimate_tokens(prompt),
        )


def build_rag_prompt(question: str, sources: list[SourceChunk]) -> str:
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

    return f"""Ты — AI-ассистент для Product Owner в B2B SaaS продукте TaskFlow AI.

Твоя задача: ответить на вопрос пользователя строго на основе предоставленного контекста.

Правила:
- Отвечай на русском языке.
- Не выдумывай факты, которых нет в контексте.
- Если в контексте нет ответа, скажи, каких данных не хватает.
- Отделяй факты из контекста от интерпретации и рекомендации.
- Если используешь числа, бери их только из контекста.
- В конце перечисли источники, которые реально использовал.

Контекст:

{context}

Вопрос пользователя:
{question}
"""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


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


def _normalize_features(features: list[str]) -> list[str]:
    return [feature.strip() for feature in features if feature.strip()]

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RagRequestLog, RagSourceLog
from app.models.chat import RagChatResponse


class RagLogService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        content_excerpt_limit: int = 1200,
    ) -> None:
        self._session_factory = session_factory
        self._content_excerpt_limit = content_excerpt_limit

    async def log_response(
        self,
        *,
        message: str,
        response: RagChatResponse,
    ) -> str:
        request_log = RagRequestLog(
            message=message,
            response=response.response,
            model=response.model,
            provider=response.provider,
            latency_ms=response.latency_ms,
            collection=response.collection,
            score_threshold=response.score_threshold,
            features=response.features,
            source_types=response.source_types,
            diversity=response.diversity,
            retrieval=response.retrieval,
            query_hints=response.query_hints,
            context_policy=response.context_policy,
            prompt_tokens_estimate=response.prompt_tokens_estimate,
        )

        request_log.sources = [
            RagSourceLog(
                source_index=index,
                qdrant_point_id=source.id,
                score=source.score,
                title=source.title,
                source_type=source.source_type,
                source_path=source.source_path,
                feature=source.feature,
                metadata_json=source.metadata,
                content_excerpt=source.content[: self._content_excerpt_limit],
            )
            for index, source in enumerate(response.sources, start=1)
        ]

        async with self._session_factory() as session:
            session.add(request_log)
            await session.commit()

        return request_log.id

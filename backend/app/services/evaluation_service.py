from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import EvaluationResult, EvaluationRun


class EvaluationService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def create_run(
        self,
        *,
        name: str,
        checklist_version: str | None,
        models: list[str],
        scenario_count: int,
        notes: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> str:
        evaluation_run = EvaluationRun(
            name=name,
            checklist_version=checklist_version,
            models=models,
            scenario_count=scenario_count,
            notes=notes,
            metadata_json=metadata or {},
        )
        async with self._session_factory() as session:
            session.add(evaluation_run)
            await session.commit()
        return evaluation_run.id

    async def add_result(
        self,
        *,
        run_id: str,
        scenario_id: str,
        scenario_name: str,
        prompt: str,
        model: str,
        provider: str | None = None,
        response: str | None = None,
        latency_ms: int | None = None,
        score_threshold: float | None = None,
        source_count: int = 0,
        sources: list[dict[str, object]] | None = None,
        retrieval: dict[str, object] | None = None,
        query_hints: dict[str, object] | None = None,
        context_policy: dict[str, object] | None = None,
        quality_flags: dict[str, object] | None = None,
        error: str | None = None,
    ) -> str:
        evaluation_result = EvaluationResult(
            run_id=run_id,
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            prompt=prompt,
            model=model,
            provider=provider,
            response=response,
            latency_ms=latency_ms,
            score_threshold=score_threshold,
            source_count=source_count,
            sources=sources or [],
            retrieval=retrieval or {},
            query_hints=query_hints or {},
            context_policy=context_policy or {},
            quality_flags=quality_flags or {},
            error=error,
        )
        async with self._session_factory() as session:
            session.add(evaluation_result)
            await session.commit()
        return evaluation_result.id

    async def complete_run(self, *, run_id: str, status: str = "completed") -> None:
        async with self._session_factory() as session:
            evaluation_run = await session.get(EvaluationRun, run_id)
            if evaluation_run is None:
                return
            evaluation_run.status = status
            evaluation_run.completed_at = datetime.now(UTC)
            await session.commit()

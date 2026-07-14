from dataclasses import dataclass
from fastapi import BackgroundTasks

from app.services.indexing_job_dispatcher import IndexingJobDispatcher


@dataclass
class _FakePublisher:
    calls: list

    async def publish_indexing_requested(self, job_ids, *, tenant_id=None, request_id=None):
        self.calls.append(
            {"job_ids": job_ids, "tenant_id": tenant_id, "request_id": request_id}
        )
        return {"published": True}


class _FakeIndexingService:
    def __init__(self) -> None:
        self.scheduled: list[list[str]] = []

    async def process_jobs(self, job_ids: list[str]) -> None:
        self.scheduled.append(job_ids)


def test_dispatcher_uses_kafka_when_enabled() -> None:
    import asyncio

    publisher = _FakePublisher(calls=[])
    service = _FakeIndexingService()
    dispatcher = IndexingJobDispatcher(
        kafka_enabled=True,
        document_indexing_service=service,  # type: ignore[arg-type]
        indexing_event_publisher=publisher,  # type: ignore[arg-type]
    )
    background = BackgroundTasks()

    async def _run() -> str:
        return await dispatcher.dispatch(
            job_ids=["job-1", "job-2"],
            background_tasks=background,
            tenant_id="local_demo",
            request_id="req-1",
        )

    mode = asyncio.run(_run())
    assert mode == "kafka"
    assert publisher.calls[0]["job_ids"] == ["job-1", "job-2"]
    assert background.tasks == []


def test_dispatcher_falls_back_to_background_tasks() -> None:
    import asyncio

    service = _FakeIndexingService()
    dispatcher = IndexingJobDispatcher(
        kafka_enabled=False,
        document_indexing_service=service,  # type: ignore[arg-type]
        indexing_event_publisher=None,
    )
    background = BackgroundTasks()

    async def _run() -> str:
        return await dispatcher.dispatch(
            job_ids=["job-9"],
            background_tasks=background,
            tenant_id="local_demo",
        )

    mode = asyncio.run(_run())
    assert mode == "background"
    assert len(background.tasks) == 1

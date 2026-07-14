import asyncio
from unittest.mock import AsyncMock

from app.services.indexing_event_publisher import IndexingEventPublisher


def test_publisher_builds_indexed_payload_shape() -> None:
    publisher = IndexingEventPublisher(
        bootstrap_servers="localhost:19092",
        topic="taskflow.indexing.requested",
        document_events_topic="taskflow.document.events",
    )
    sent: list[tuple[str, dict]] = []

    async def _fake_send(*, topic: str, payload: dict, key: str) -> None:
        sent.append((topic, payload))

    publisher._send = _fake_send  # type: ignore[method-assign]

    async def _run() -> None:
        await publisher.publish_document_indexed(
            job_id="job-1",
            document_id="doc-1",
            bucket_id="bucket-1",
            tenant_id="local_demo",
            chunks_indexed=3,
        )
        await publisher.publish_document_index_failed(
            job_id="job-2",
            document_id="doc-2",
            bucket_id="bucket-1",
            tenant_id="local_demo",
            error="boom",
        )

    asyncio.run(_run())
    assert sent[0][0] == "taskflow.document.events"
    assert sent[0][1]["event_type"] == "document.indexed"
    assert sent[0][1]["chunks_indexed"] == 3
    assert sent[1][1]["event_type"] == "document.index_failed"
    assert sent[1][1]["error"] == "boom"


def test_process_job_publishes_indexed_event() -> None:
    """DocumentIndexingService should emit lifecycle event when publisher is set."""
    from app.services.document_indexing_service import DocumentIndexingService

    publisher = AsyncMock()
    publisher.publish_document_indexed = AsyncMock(return_value={"published": True})
    publisher.publish_document_index_failed = AsyncMock(return_value={"published": True})

    service = DocumentIndexingService(
        session_factory=AsyncMock(),  # type: ignore[arg-type]
        qdrant_store=AsyncMock(),  # type: ignore[arg-type]
        ollama_client=AsyncMock(),  # type: ignore[arg-type]
        embedding_model="nomic-embed-text",
        event_publisher=publisher,
    )

    async def _run() -> None:
        await service._publish_indexed(
            job_id="j1",
            document_id="d1",
            bucket_id="b1",
            tenant_id="t1",
            chunks_indexed=2,
        )

    asyncio.run(_run())
    publisher.publish_document_indexed.assert_awaited_once()

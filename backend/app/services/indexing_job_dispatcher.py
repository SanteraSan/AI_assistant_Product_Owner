"""Dispatch indexing jobs via Kafka or in-process BackgroundTasks."""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks

from app.services.document_indexing_service import DocumentIndexingService
from app.services.indexing_event_publisher import IndexingEventPublisher

logger = logging.getLogger(__name__)


class IndexingJobDispatcher:
    def __init__(
        self,
        *,
        kafka_enabled: bool,
        document_indexing_service: DocumentIndexingService | None,
        indexing_event_publisher: IndexingEventPublisher | None,
    ) -> None:
        self._kafka_enabled = kafka_enabled
        self._document_indexing_service = document_indexing_service
        self._indexing_event_publisher = indexing_event_publisher

    @property
    def kafka_enabled(self) -> bool:
        return self._kafka_enabled and self._indexing_event_publisher is not None

    async def dispatch(
        self,
        *,
        job_ids: list[str],
        background_tasks: BackgroundTasks,
        tenant_id: str | None = None,
        request_id: str | None = None,
    ) -> str:
        if not job_ids:
            return "noop"
        if self.kafka_enabled:
            assert self._indexing_event_publisher is not None
            await self._indexing_event_publisher.publish_indexing_requested(
                job_ids,
                tenant_id=tenant_id,
                request_id=request_id,
            )
            return "kafka"
        if self._document_indexing_service is not None:
            background_tasks.add_task(self._document_indexing_service.process_jobs, job_ids)
            return "background"
        logger.warning("Indexing jobs created but no dispatcher path available: %s", job_ids)
        return "noop"

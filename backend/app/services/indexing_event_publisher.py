"""Publish document indexing requests and lifecycle events to Kafka (E5/E5.x)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from aiokafka import AIOKafkaProducer

logger = logging.getLogger(__name__)


class IndexingEventPublisher:
    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic: str,
        document_events_topic: str | None = None,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._document_events_topic = document_events_topic or topic
        self._producer: AIOKafkaProducer | None = None

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def document_events_topic(self) -> str:
        return self._document_events_topic

    async def start(self) -> None:
        if self._producer is not None:
            return
        producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await producer.start()
        self._producer = producer
        logger.info(
            "Kafka indexing producer started bootstrap=%s request_topic=%s events_topic=%s",
            self._bootstrap_servers,
            self._topic,
            self._document_events_topic,
        )

    async def stop(self) -> None:
        if self._producer is None:
            return
        await self._producer.stop()
        self._producer = None

    async def publish_indexing_requested(
        self,
        job_ids: list[str],
        *,
        tenant_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not job_ids:
            return {"published": False, "reason": "empty_job_ids"}
        payload = {
            "event_type": "indexing.requested",
            "event_id": str(uuid4()),
            "job_ids": list(job_ids),
            "tenant_id": tenant_id,
            "request_id": request_id,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        await self._send(topic=self._topic, payload=payload, key=job_ids[0])
        logger.info(
            "Published indexing.requested jobs=%s event_id=%s",
            job_ids,
            payload["event_id"],
        )
        return {"published": True, "payload": payload}

    async def publish_document_indexed(
        self,
        *,
        job_id: str,
        document_id: str,
        bucket_id: str,
        tenant_id: str,
        chunks_indexed: int,
    ) -> dict[str, Any]:
        payload = {
            "event_type": "document.indexed",
            "event_id": str(uuid4()),
            "job_id": job_id,
            "document_id": document_id,
            "bucket_id": bucket_id,
            "tenant_id": tenant_id,
            "chunks_indexed": chunks_indexed,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        await self._send(topic=self._document_events_topic, payload=payload, key=document_id)
        logger.info(
            "Published document.indexed job=%s document=%s chunks=%s",
            job_id,
            document_id,
            chunks_indexed,
        )
        return {"published": True, "payload": payload}

    async def publish_document_index_failed(
        self,
        *,
        job_id: str,
        document_id: str | None,
        bucket_id: str | None,
        tenant_id: str | None,
        error: str,
    ) -> dict[str, Any]:
        payload = {
            "event_type": "document.index_failed",
            "event_id": str(uuid4()),
            "job_id": job_id,
            "document_id": document_id,
            "bucket_id": bucket_id,
            "tenant_id": tenant_id,
            "error": error[:2000],
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        key = document_id or job_id
        await self._send(topic=self._document_events_topic, payload=payload, key=key)
        logger.info(
            "Published document.index_failed job=%s document=%s",
            job_id,
            document_id,
        )
        return {"published": True, "payload": payload}

    async def _send(self, *, topic: str, payload: dict[str, Any], key: str) -> None:
        if self._producer is None:
            await self.start()
        assert self._producer is not None
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await self._producer.send_and_wait(topic, body, key=key.encode("utf-8"))

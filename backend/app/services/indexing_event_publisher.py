"""Publish document indexing requests to Kafka (E5)."""

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
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer: AIOKafkaProducer | None = None

    @property
    def topic(self) -> str:
        return self._topic

    async def start(self) -> None:
        if self._producer is not None:
            return
        producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await producer.start()
        self._producer = producer
        logger.info(
            "Kafka indexing producer started bootstrap=%s topic=%s",
            self._bootstrap_servers,
            self._topic,
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
        if self._producer is None:
            await self.start()
        assert self._producer is not None
        payload = {
            "event_type": "indexing.requested",
            "event_id": str(uuid4()),
            "job_ids": list(job_ids),
            "tenant_id": tenant_id,
            "request_id": request_id,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # Key by first job id for stable partition affinity on retries.
        await self._producer.send_and_wait(self._topic, body, key=job_ids[0].encode("utf-8"))
        logger.info(
            "Published indexing.requested jobs=%s event_id=%s",
            job_ids,
            payload["event_id"],
        )
        return {"published": True, "payload": payload}

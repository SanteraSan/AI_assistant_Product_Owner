#!/usr/bin/env python3
"""Kafka/Redpanda consumer: indexing.requested → DocumentIndexingService.process_jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiokafka import AIOKafkaConsumer

from app.clients.qdrant_store import QdrantStore
from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.document_indexing_service import DocumentIndexingService
from app.services.ollama_client import OllamaClient
from app.services.ollama_load_guard import OllamaLoadGuard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("indexing_worker")


async def run_worker() -> None:
    settings = get_settings()
    engine = create_engine(settings.postgres_dsn)
    session_factory = create_session_factory(engine)
    qdrant_store = QdrantStore(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        check_compatibility=settings.qdrant_check_compatibility,
    )
    ollama_client = OllamaClient(
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.request_timeout_seconds,
        load_guard=OllamaLoadGuard(
            max_concurrency=settings.ollama_max_concurrency,
            timeout_seconds=settings.ollama_queue_timeout_seconds,
        ),
    )
    event_publisher = None
    if settings.kafka_enabled:
        from app.services.indexing_event_publisher import IndexingEventPublisher

        event_publisher = IndexingEventPublisher(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            topic=settings.kafka_indexing_topic,
            document_events_topic=settings.kafka_document_events_topic,
        )
        await event_publisher.start()
    indexing_service = DocumentIndexingService(
        session_factory=session_factory,
        qdrant_store=qdrant_store,
        ollama_client=ollama_client,
        embedding_model=settings.embedding_model,
        image_vision_enabled=settings.image_vision_enabled,
        image_vision_model=settings.image_vision_model,
        event_publisher=event_publisher,
    )

    consumer = AIOKafkaConsumer(
        settings.kafka_indexing_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    logger.info(
        "Indexing worker started topic=%s group=%s bootstrap=%s",
        settings.kafka_indexing_topic,
        settings.kafka_consumer_group,
        settings.kafka_bootstrap_servers,
    )
    try:
        async for message in consumer:
            try:
                payload = json.loads(message.value.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                logger.exception("Invalid Kafka payload; committing offset to skip poison message")
                await consumer.commit()
                continue
            event_type = payload.get("event_type")
            job_ids = payload.get("job_ids") or []
            if event_type != "indexing.requested" or not isinstance(job_ids, list) or not job_ids:
                logger.warning("Skipping unexpected payload: %s", payload)
                await consumer.commit()
                continue
            clean_ids = [str(job_id) for job_id in job_ids if str(job_id).strip()]
            logger.info(
                "Received indexing.requested event_id=%s jobs=%s",
                payload.get("event_id"),
                clean_ids,
            )
            await indexing_service.process_jobs(clean_ids)
            await consumer.commit()
            logger.info("Completed indexing.requested jobs=%s", clean_ids)
    finally:
        await consumer.stop()
        if event_publisher is not None:
            await event_publisher.stop()
        await ollama_client.aclose()
        await engine.dispose()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

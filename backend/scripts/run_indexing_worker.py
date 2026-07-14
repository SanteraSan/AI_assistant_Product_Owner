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
from app.db.session import create_engine, create_session_factory, database_available
from app.services.document_indexing_service import DocumentIndexingService
from app.services.metrics import AppMetrics
from app.services.ollama_client import OllamaClient
from app.services.ollama_load_guard import OllamaLoadGuard
from app.services.worker_health import serve_worker_health

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
    from app.services.object_storage import build_object_storage, resolve_upload_root

    object_storage = build_object_storage(
        enabled=settings.object_storage_enabled,
        upload_root=resolve_upload_root(settings.raw_data_dir),
        endpoint_url=settings.object_storage_endpoint,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key,
        bucket=settings.object_storage_bucket,
        region=settings.object_storage_region,
    )
    ollama_client = OllamaClient(
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.request_timeout_seconds,
        load_guard=OllamaLoadGuard(
            max_concurrency=settings.ollama_max_concurrency,
            timeout_seconds=settings.ollama_queue_timeout_seconds,
        ),
    )
    app_metrics = AppMetrics(enabled=settings.metrics_enabled)
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
        object_storage=object_storage,
        metrics=app_metrics,
    )

    consumer_started = False
    consumer: AIOKafkaConsumer | None = None

    async def ready_probe() -> dict[str, object]:
        dependencies: dict[str, object] = {
            "postgres_available": await database_available(engine),
            "consumer_started": consumer_started,
            "kafka_enabled": settings.kafka_enabled,
            "object_storage_enabled": settings.object_storage_enabled,
        }
        if settings.kafka_enabled:
            dependencies["kafka_bootstrap_servers"] = settings.kafka_bootstrap_servers
        ready = bool(dependencies["postgres_available"]) and (
            consumer_started if settings.kafka_enabled else True
        )
        return {
            "status": "ready" if ready else "degraded",
            "service": "indexing-worker",
            "dependencies": dependencies,
        }

    health_server = await serve_worker_health(
        host=settings.indexing_worker_health_host,
        port=settings.indexing_worker_health_port,
        ready_probe=ready_probe,
        metrics=app_metrics,
    )
    health_task = asyncio.create_task(health_server.serve(), name="worker-health")

    if settings.kafka_enabled:
        consumer = AIOKafkaConsumer(
            settings.kafka_indexing_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        consumer_started = True
        logger.info(
            "Indexing worker started topic=%s group=%s bootstrap=%s",
            settings.kafka_indexing_topic,
            settings.kafka_consumer_group,
            settings.kafka_bootstrap_servers,
        )
    else:
        logger.warning(
            "KAFKA_ENABLED=false: worker health is up, but no Kafka consumer is running"
        )

    try:
        if consumer is None:
            await health_task
            return
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
        health_server.should_exit = True
        await health_task
        if consumer is not None:
            await consumer.stop()
        if event_publisher is not None:
            await event_publisher.stop()
        await ollama_client.aclose()
        await engine.dispose()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

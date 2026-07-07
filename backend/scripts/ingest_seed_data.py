import argparse
import asyncio
import uuid
from pathlib import Path

from app.clients.qdrant_store import QdrantStore
from app.core.config import get_settings
from app.services.chunking import DocumentChunk, chunk_documents
from app.services.document_loader import load_raw_documents
from app.services.ollama_client import OllamaClient


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TaskFlow AI seed data into Qdrant.")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the target collection.")
    parser.add_argument("--batch-size", type=int, default=32, help="Number of chunks to upsert per batch.")
    args = parser.parse_args()

    settings = get_settings()
    raw_data_dir = (Path(__file__).resolve().parents[1] / settings.raw_data_dir).resolve()

    documents = load_raw_documents(
        raw_data_dir,
        tenant_id=settings.default_tenant_id,
        bucket_id=settings.default_bucket_id,
    )
    chunks = chunk_documents(documents)

    if not chunks:
        raise SystemExit(f"No chunks produced from raw data dir: {raw_data_dir}")

    ollama_client = OllamaClient(
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )
    qdrant_store = QdrantStore(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
    )

    print(f"Raw data dir: {raw_data_dir}")
    print(f"Documents loaded: {len(documents)}")
    print(f"Chunks produced: {len(chunks)}")
    print(f"Embedding model: {settings.embedding_model}")
    print(f"Qdrant collection: {settings.qdrant_collection}")
    print(f"Tenant ID: {settings.default_tenant_id}")
    print(f"Bucket ID: {settings.default_bucket_id}")

    first_vector = await ollama_client.embed(settings.embedding_model, chunks[0].content)
    qdrant_store.ensure_collection(vector_size=len(first_vector), recreate=args.recreate)

    first_payload = _payload_for_chunk(chunks[0])
    pending: list[tuple[str, list[float], dict[str, object]]] = [
        (_point_id_for_chunk(chunks[0]), first_vector, first_payload)
    ]

    for chunk in chunks[1:]:
        vector = await ollama_client.embed(settings.embedding_model, chunk.content)
        pending.append((_point_id_for_chunk(chunk), vector, _payload_for_chunk(chunk)))
        if len(pending) >= args.batch_size:
            qdrant_store.upsert_chunks(pending)
            print(f"Upserted chunks: {len(pending)}")
            pending.clear()

    if pending:
        qdrant_store.upsert_chunks(pending)
        print(f"Upserted chunks: {len(pending)}")

    print("Ingestion complete.")


def _point_id_for_chunk(chunk: DocumentChunk) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.id))


def _payload_for_chunk(chunk: DocumentChunk) -> dict[str, object]:
    return {
        "document_id": chunk.document_id,
        "tenant_id": chunk.tenant_id,
        "bucket_id": chunk.bucket_id,
        "chunk_id": chunk.id,
        "chunk_index": chunk.chunk_index,
        "domain": chunk.domain,
        "source_type": chunk.source_type,
        "source_path": chunk.source_path,
        "processing_status": chunk.processing_status,
        "title": chunk.title,
        "content": chunk.content,
        "feature": chunk.feature,
        "document_metadata": chunk.metadata,
        "language": "ru",
    }


if __name__ == "__main__":
    asyncio.run(main())

from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.models.chat import SourceChunk


class QdrantStore:
    def __init__(self, url: str, collection_name: str) -> None:
        self._client = QdrantClient(url=url)
        self._collection_name = collection_name

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def collection_exists(self) -> bool:
        return self._client.collection_exists(self._collection_name)

    def ensure_collection(self, vector_size: int, recreate: bool = False) -> None:
        if recreate and self.collection_exists():
            self._client.delete_collection(self._collection_name)

        if self.collection_exists():
            return

        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    def upsert_chunks(self, chunks: list[tuple[str, list[float], dict[str, Any]]]) -> None:
        points = [
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
            for point_id, vector, payload in chunks
        ]
        self._client.upsert(collection_name=self._collection_name, points=points)

    def search(
        self,
        query_vector: list[float],
        limit: int,
        tenant_id: str | None = None,
        bucket_ids: list[str] | None = None,
        features: list[str] | None = None,
        source_types: list[str] | None = None,
        document_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
    ) -> list[SourceChunk]:
        result = self._client.query_points(
            collection_name=self._collection_name,
            query=query_vector,
            query_filter=_payload_filter(
                tenant_id=tenant_id,
                bucket_ids=bucket_ids or [],
                features=features or [],
                source_types=source_types or [],
                document_ids=document_ids or [],
                source_paths=source_paths or [],
            ),
            limit=limit,
            with_payload=True,
        )

        sources: list[SourceChunk] = []
        for point in result.points:
            payload = point.payload or {}
            sources.append(_source_from_payload(id=str(point.id), score=point.score, payload=payload))
        return sources

    def scroll(
        self,
        *,
        limit: int,
        tenant_id: str | None = None,
        bucket_ids: list[str] | None = None,
        features: list[str] | None = None,
        source_types: list[str] | None = None,
        document_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
    ) -> list[SourceChunk]:
        records, _ = self._client.scroll(
            collection_name=self._collection_name,
            scroll_filter=_payload_filter(
                tenant_id=tenant_id,
                bucket_ids=bucket_ids or [],
                features=features or [],
                source_types=source_types or [],
                document_ids=document_ids or [],
                source_paths=source_paths or [],
            ),
            limit=limit,
            with_payload=True,
        )

        sources: list[SourceChunk] = []
        for record in records:
            payload = record.payload or {}
            sources.append(_source_from_payload(id=str(record.id), score=None, payload=payload))
        return sources


def _source_from_payload(
    *,
    id: str,
    score: float | None,
    payload: dict[str, Any],
) -> SourceChunk:
    content = str(payload.get("content", ""))
    return SourceChunk(
        id=id,
        score=score,
        title=_as_optional_str(payload.get("title")),
        source_type=_as_optional_str(payload.get("source_type")),
        source_path=_as_optional_str(payload.get("source_path")),
        feature=_as_str_list(payload.get("feature")),
        content=content,
        metadata={
            key: value
            for key, value in payload.items()
            if key not in {"content", "title", "source_type", "source_path", "feature"}
        },
    )


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _payload_filter(
    tenant_id: str | None,
    bucket_ids: list[str],
    features: list[str],
    source_types: list[str],
    document_ids: list[str],
    source_paths: list[str],
) -> models.Filter | None:
    conditions: list[models.FieldCondition] = []

    normalized_tenant_id = tenant_id.strip() if tenant_id else ""
    if normalized_tenant_id:
        conditions.append(
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value=normalized_tenant_id),
            )
        )

    normalized_bucket_ids = [bucket_id.strip() for bucket_id in bucket_ids if bucket_id.strip()]
    if normalized_bucket_ids:
        conditions.append(
            models.FieldCondition(
                key="bucket_id",
                match=models.MatchAny(any=normalized_bucket_ids),
            )
        )

    normalized = [feature.strip() for feature in features if feature.strip()]
    if normalized:
        conditions.append(
            models.FieldCondition(
                key="feature",
                match=models.MatchAny(any=normalized),
            )
        )

    normalized_source_types = [source_type.strip() for source_type in source_types if source_type.strip()]
    if normalized_source_types:
        conditions.append(
            models.FieldCondition(
                key="source_type",
                match=models.MatchAny(any=normalized_source_types),
            )
        )

    normalized_document_ids = [document_id.strip() for document_id in document_ids if document_id.strip()]
    if normalized_document_ids:
        conditions.append(
            models.FieldCondition(
                key="document_id",
                match=models.MatchAny(any=normalized_document_ids),
            )
        )

    normalized_source_paths = [source_path.strip() for source_path in source_paths if source_path.strip()]
    if normalized_source_paths:
        conditions.append(
            models.FieldCondition(
                key="source_path",
                match=models.MatchAny(any=normalized_source_paths),
            )
        )

    if not conditions:
        return None
    return models.Filter(must=conditions)

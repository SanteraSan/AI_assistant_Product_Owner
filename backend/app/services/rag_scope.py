from __future__ import annotations

from app.db.models import DocumentAsset
from app.services.access_policy import UserContext
from app.services.bucket_service import BucketService


async def resolve_rag_document_ids(
    *,
    user: UserContext,
    bucket_service: BucketService,
    requested_document_ids: list[str] | None,
    bucket_documents: list[DocumentAsset],
) -> list[str]:
    """Authorize document scope before Qdrant retrieval.

    - explicit document_ids are intersected with can_read_document
    - bucket-scoped docs come from already-filtered bucket_documents
    - empty scope falls back to indexed available documents for the user
    """
    if requested_document_ids:
        allowed: list[str] = []
        seen: set[str] = set()
        for document_id in requested_document_ids:
            cleaned = document_id.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            document = await bucket_service.get_document(user=user, document_id=cleaned)
            if document is None:
                continue
            if document.status != "indexed":
                continue
            allowed.append(document.id)
        return allowed

    if bucket_documents:
        return [document.id for document in bucket_documents if document.status == "indexed"]

    available = await bucket_service.list_available_documents(user=user)
    return [document.id for document in available if document.status == "indexed"]

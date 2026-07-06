from dataclasses import dataclass

from app.services.document_loader import RawDocument


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    document_id: str
    title: str
    content: str
    source_type: str
    source_path: str
    domain: str
    feature: list[str]
    chunk_index: int


def chunk_documents(
    documents: list[RawDocument],
    *,
    max_chars: int = 1800,
    overlap_chars: int = 200,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for document in documents:
        parts = _split_text(document.content, max_chars=max_chars, overlap_chars=overlap_chars)
        for index, part in enumerate(parts):
            chunks.append(
                DocumentChunk(
                    id=f"{document.id}:chunk:{index}",
                    document_id=document.id,
                    title=document.title,
                    content=part,
                    source_type=document.source_type,
                    source_path=document.source_path,
                    domain=document.domain,
                    feature=document.feature,
                    chunk_index=index,
                )
            )
    return chunks


def _split_text(text: str, *, max_chars: int, overlap_chars: int) -> list[str]:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(normalized):
            break
        start = max(0, end - overlap_chars)
    return chunks

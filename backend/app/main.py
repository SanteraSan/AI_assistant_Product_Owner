from time import perf_counter

import httpx
from fastapi import FastAPI, HTTPException

from app.clients.qdrant_store import QdrantStore
from app.core.config import get_settings
from app.models.chat import ChatRequest, ChatResponse, RagChatRequest, RagChatResponse
from app.services.feature_extractor import FeatureExtractor
from app.services.ollama_client import OllamaClient
from app.services.rag_service import RagService


settings = get_settings()
app = FastAPI(title=settings.app_name)
ollama_client = OllamaClient(
    base_url=settings.ollama_base_url,
    timeout_seconds=settings.request_timeout_seconds,
)
qdrant_store = QdrantStore(
    url=settings.qdrant_url,
    collection_name=settings.qdrant_collection,
)
feature_extractor = FeatureExtractor()
rag_service = RagService(
    ollama_client=ollama_client,
    qdrant_store=qdrant_store,
    feature_extractor=feature_extractor,
    embedding_model=settings.embedding_model,
    default_model=settings.default_rag_model,
    default_top_k=settings.rag_top_k,
    default_score_threshold=settings.rag_score_threshold,
)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "ollama_available": await ollama_client.health(),
        "default_model": settings.default_model,
        "default_rag_model": settings.default_rag_model,
        "embedding_model": settings.embedding_model,
        "qdrant_collection": settings.qdrant_collection,
        "qdrant_collection_exists": _qdrant_collection_exists(),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    model = request.model or settings.default_model
    started_at = perf_counter()

    try:
        result = await ollama_client.generate(model=model, prompt=request.message)
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not reachable. Check that `ollama serve` is running.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    latency_ms = int((perf_counter() - started_at) * 1000)

    return ChatResponse(
        model=model,
        response=result.get("response", ""),
        latency_ms=latency_ms,
    )


@app.post("/rag/chat", response_model=RagChatResponse)
async def rag_chat(request: RagChatRequest) -> RagChatResponse:
    if not _qdrant_collection_exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Qdrant collection is not ready. Run "
                "`python -m scripts.ingest_seed_data --recreate` from the backend directory."
            ),
        )

    try:
        return await rag_service.answer(
            message=request.message,
            model=request.model,
            top_k=request.top_k,
            score_threshold=request.score_threshold,
            features=request.features,
        )
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not reachable. Check that `ollama serve` is running.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _qdrant_collection_exists() -> bool:
    try:
        return qdrant_store.collection_exists()
    except Exception:
        return False

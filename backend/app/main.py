from time import perf_counter

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.ollama_client import OllamaClient


settings = get_settings()
app = FastAPI(title=settings.app_name)
ollama_client = OllamaClient(
    base_url=settings.ollama_base_url,
    timeout_seconds=settings.request_timeout_seconds,
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    model: str | None = None


class ChatResponse(BaseModel):
    model: str
    response: str
    latency_ms: int
    provider: str = "ollama"


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "ollama_available": await ollama_client.health(),
        "default_model": settings.default_model,
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

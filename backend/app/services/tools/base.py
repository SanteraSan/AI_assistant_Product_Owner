from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from app.services.access_policy import UserContext

ToolStatus = Literal["ok", "denied", "invalid_input", "failed"]

RESULT_PREVIEW_LIMIT = 500


@dataclass(frozen=True)
class ToolContext:
    user: UserContext
    request_id: str
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_audit_entry(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        latency_ms: int,
    ) -> dict[str, Any]:
        return {
            "id": call_id,
            "name": name,
            "arguments": arguments,
            "status": self.status,
            "latency_ms": latency_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "result_preview": _preview(self.data) if self.ok else None,
        }

    def to_llm_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.ok:
            payload["data"] = self.data or {}
        else:
            payload["error_code"] = self.error_code
            payload["error_message"] = self.error_message
        return payload


class Tool(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolResult: ...


def tool_ok(data: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(status="ok", data=data or {})


def tool_denied(*, error_code: str, error_message: str) -> ToolResult:
    return ToolResult(status="denied", error_code=error_code, error_message=error_message)


def tool_invalid(*, error_code: str, error_message: str) -> ToolResult:
    return ToolResult(
        status="invalid_input",
        error_code=error_code,
        error_message=error_message,
    )


def tool_failed(*, error_code: str, error_message: str) -> ToolResult:
    return ToolResult(status="failed", error_code=error_code, error_message=error_message)


def _preview(data: dict[str, Any] | None) -> str | None:
    if data is None:
        return None
    text = str(data)
    if len(text) <= RESULT_PREVIEW_LIMIT:
        return text
    return text[: RESULT_PREVIEW_LIMIT - 3] + "..."

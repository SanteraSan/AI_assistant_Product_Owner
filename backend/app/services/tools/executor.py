from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ToolCallLog
from app.services.access_policy import UserContext
from app.services.tools.base import (
    ToolContext,
    ToolResult,
    tool_denied,
    tool_failed,
    tool_invalid,
)
from app.services.tools.permissions import can_invoke_tool, required_roles_for
from app.services.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ToolExecution:
    result: ToolResult
    audit_entry: dict[str, Any]


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        result_preview_limit: int = 500,
    ) -> None:
        self._registry = registry
        self._session_factory = session_factory
        self._result_preview_limit = result_preview_limit

    async def execute(
        self,
        *,
        name: str,
        arguments: dict[str, Any] | None,
        user: UserContext,
        request_id: str,
        extras: dict[str, Any] | None = None,
    ) -> ToolExecution:
        call_id = f"tc_{uuid4().hex[:12]}"
        started = perf_counter()
        args = dict(arguments or {})

        tool = self._registry.get(name)
        if tool is None:
            result = tool_invalid(
                error_code="unknown_tool",
                error_message=f"Unknown tool: {name}",
            )
            return await self._finish(
                call_id=call_id,
                name=name,
                arguments=args,
                user=user,
                request_id=request_id,
                result=result,
                started=started,
            )

        if not can_invoke_tool(tool_name=name, roles=user.roles):
            required = required_roles_for(name)
            result = tool_denied(
                error_code="tool_forbidden",
                error_message=(
                    f"Role not allowed to call tool '{name}'."
                    + (f" Required roles: {sorted(required)}." if required else "")
                ),
            )
            return await self._finish(
                call_id=call_id,
                name=name,
                arguments=args,
                user=user,
                request_id=request_id,
                result=result,
                started=started,
            )

        try:
            parsed_args = tool.args_model.model_validate(args)
        except ValidationError as exc:
            result = tool_invalid(
                error_code="invalid_arguments",
                error_message=str(exc.errors()),
            )
            return await self._finish(
                call_id=call_id,
                name=name,
                arguments=args,
                user=user,
                request_id=request_id,
                result=result,
                started=started,
            )

        ctx = ToolContext(user=user, request_id=request_id, extras=extras or {})
        try:
            result = await tool.run(ctx, parsed_args)
        except Exception as exc:  # noqa: BLE001 — agent loop must see ToolResult, not crash
            result = tool_failed(
                error_code="tool_execution_error",
                error_message=str(exc),
            )

        return await self._finish(
            call_id=call_id,
            name=name,
            arguments=parsed_args.model_dump(mode="json"),
            user=user,
            request_id=request_id,
            result=result,
            started=started,
        )

    async def _finish(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        user: UserContext,
        request_id: str,
        result: ToolResult,
        started: float,
    ) -> ToolExecution:
        latency_ms = int((perf_counter() - started) * 1000)
        audit_entry = result.to_audit_entry(
            call_id=call_id,
            name=name,
            arguments=arguments,
            latency_ms=latency_ms,
        )
        await self._persist_audit(
            call_id=call_id,
            name=name,
            arguments=arguments,
            user=user,
            request_id=request_id,
            result=result,
            latency_ms=latency_ms,
        )
        return ToolExecution(result=result, audit_entry=audit_entry)

    async def _persist_audit(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        user: UserContext,
        request_id: str,
        result: ToolResult,
        latency_ms: int,
    ) -> None:
        if self._session_factory is None:
            return
        preview = None
        if result.ok and result.data is not None:
            text = str(result.data)
            preview = text[: self._result_preview_limit]
        log = ToolCallLog(
            id=call_id,
            request_id=request_id,
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            tool_name=name,
            arguments_json=arguments,
            status=result.status,
            error_code=result.error_code,
            error_message=result.error_message,
            latency_ms=latency_ms,
            result_preview=preview,
        )
        async with self._session_factory() as session:
            session.add(log)
            await session.commit()

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolLoopParseResult:
    tool_calls: list[ParsedToolCall]
    final_answer: str | None
    raw_json: dict[str, Any] | None
    error: str | None = None


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


_RESERVED_KEYS = {"tool_calls", "final_answer"}


def parse_tool_loop_response(
    text: str,
    *,
    tool_names: set[str] | None = None,
) -> ToolLoopParseResult:
    """Parse portable JSON tool-loop payload from model output.

    Expected shapes:
    - {"tool_calls": [{"name": "...", "arguments": {...}}, ...]}
    - {"final_answer": "..."}
    - both keys allowed; empty tool_calls + final_answer ends the loop
    """
    try:
        raw = _extract_json_object(text)
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        return ToolLoopParseResult(
            tool_calls=[],
            final_answer=None,
            raw_json=None,
            error=f"invalid_json:{exc}",
        )

    if not isinstance(parsed, dict):
        return ToolLoopParseResult(
            tool_calls=[],
            final_answer=None,
            raw_json=None,
            error="json_not_object",
        )

    tool_calls: list[ParsedToolCall] = []
    raw_calls = parsed.get("tool_calls")
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, list):
        return ToolLoopParseResult(
            tool_calls=[],
            final_answer=None,
            raw_json=parsed,
            error="tool_calls_not_list",
        )

    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        arguments = item.get("arguments")
        if arguments is None:
            arguments = item.get("args") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        tool_calls.append(ParsedToolCall(name=name, arguments=arguments))

    if not tool_calls:
        tool_calls.extend(_shorthand_tool_calls(parsed, tool_names))

    final_answer = parsed.get("final_answer")
    if final_answer is not None:
        if isinstance(final_answer, (list, dict)):
            # Models sometimes emit []/{} instead of a string; treat empties as missing.
            if not final_answer:
                final_answer = None
            else:
                final_answer = json.dumps(final_answer, ensure_ascii=False)
        else:
            final_answer = str(final_answer).strip() or None

    return ToolLoopParseResult(
        tool_calls=tool_calls,
        final_answer=final_answer,
        raw_json=parsed,
        error=None,
    )


def _shorthand_tool_calls(
    parsed: dict[str, Any],
    tool_names: set[str] | None,
) -> list[ParsedToolCall]:
    """Accept a tool call that skipped the tool_calls envelope.

    qwen often emits {"rag_search": {"query": "..."}} instead of
    {"tool_calls": [{"name": "rag_search", "arguments": {...}}]}.
    """
    name = str(parsed.get("name") or "").strip()
    arguments = parsed.get("arguments")
    if _is_known_tool(name, tool_names) and isinstance(arguments, dict):
        return [ParsedToolCall(name=name, arguments=arguments)]

    calls: list[ParsedToolCall] = []
    for key, value in parsed.items():
        if key in _RESERVED_KEYS or not isinstance(value, dict):
            continue
        if not _is_known_tool(key, tool_names):
            continue
        calls.append(ParsedToolCall(name=key, arguments=value))
    return calls


def _is_known_tool(name: str, tool_names: set[str] | None) -> bool:
    if not name:
        return False
    if tool_names is None:
        return False
    return name in tool_names


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    fence = _FENCE_RE.search(stripped)
    if fence:
        stripped = fence.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response did not contain a JSON object")
    return stripped[start : end + 1]

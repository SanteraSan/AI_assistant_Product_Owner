from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.services.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def list_specs(self) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for name in self.names():
            tool = self._tools[name]
            specs.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": _schema_for(tool.args_model),
                }
            )
        return specs


def _schema_for(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    # Keep agent prompts compact: drop noisy $defs expansion when unused.
    return {
        "type": schema.get("type", "object"),
        "properties": schema.get("properties", {}),
        "required": schema.get("required", []),
    }

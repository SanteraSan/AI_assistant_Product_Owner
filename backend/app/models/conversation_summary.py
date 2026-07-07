from typing import Any

from pydantic import BaseModel, Field


class LlmStructuredSummary(BaseModel):
    main_topics: list[str] = Field(default_factory=list)
    user_goals: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)

    def to_compact_dict(self) -> dict[str, object]:
        return {
            "main_topics": _compact_str_list(self.main_topics),
            "user_goals": _compact_str_list(self.user_goals),
            "decisions": _compact_str_list(self.decisions),
            "open_questions": _compact_str_list(self.open_questions),
            "constraints": _compact_str_list(self.constraints),
            "summary": " ".join(self.summary.split())[:1200],
        }


def _compact_str_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        compact = " ".join(item.split())
        if not compact or compact in normalized:
            continue
        normalized.append(compact[:240])
        if len(normalized) >= limit:
            break
    return normalized

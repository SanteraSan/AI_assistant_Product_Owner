from app.services.chat_history_service import ChatHistoryMessage


class ConversationMemoryService:
    def __init__(
        self,
        *,
        enabled: bool = True,
        token_budget: int = 350,
        recent_messages_limit: int = 4,
    ) -> None:
        self._enabled = enabled
        self._token_budget = max(0, token_budget)
        self._recent_messages_limit = max(0, recent_messages_limit)

    @property
    def recent_messages_limit(self) -> int:
        return self._recent_messages_limit

    def build_prompt_memory(
        self,
        *,
        recent_messages: list[ChatHistoryMessage],
        summary_context: dict[str, object],
    ) -> dict[str, object]:
        if not self._enabled:
            return self.empty_prompt_memory(reason="disabled")

        if self._token_budget <= 0:
            return self.empty_prompt_memory(reason="zero_budget")

        if summary_context.get("topic_switch_detected") is True:
            return self.empty_prompt_memory(reason="topic_switch")

        parts: list[str] = []
        included: list[str] = []
        token_estimate = 0

        structured_summary = _as_dict(summary_context.get("summary_structured"))
        summary_text = str(structured_summary.get("summary") or "").strip()
        if not summary_text:
            summary_text = str(summary_context.get("summary") or "").strip()

        if summary_text:
            token_estimate = _try_add_memory_part(
                parts=parts,
                included=included,
                label="summary",
                text=f"Summary диалога: {summary_text}",
                token_budget=self._token_budget,
                token_estimate=token_estimate,
            )

        user_goals = _string_list(structured_summary.get("user_goals"))
        if user_goals:
            token_estimate = _try_add_memory_part(
                parts=parts,
                included=included,
                label="user_goals",
                text="Цели пользователя: " + "; ".join(user_goals[:3]),
                token_budget=self._token_budget,
                token_estimate=token_estimate,
            )

        recent_user_messages = [
            message.content.strip()
            for message in recent_messages
            if message.role == "user" and message.content.strip()
        ][-self._recent_messages_limit:]
        if recent_user_messages:
            recent_text = "\n".join(f"- {message}" for message in recent_user_messages)
            token_estimate = _try_add_memory_part(
                parts=parts,
                included=included,
                label="recent_user_messages",
                text=f"Последние сообщения пользователя:\n{recent_text}",
                token_budget=self._token_budget,
                token_estimate=token_estimate,
            )

        content = "\n".join(parts).strip()
        return {
            "used": bool(content),
            "reason": "included" if content else "no_memory_content",
            "token_budget": self._token_budget,
            "token_estimate": token_estimate,
            "included": included,
            "content": content,
        }

    def empty_prompt_memory(self, *, reason: str) -> dict[str, object]:
        return {
            "used": False,
            "reason": reason,
            "token_budget": self._token_budget,
            "token_estimate": 0,
            "included": [],
            "content": "",
        }


def _try_add_memory_part(
    *,
    parts: list[str],
    included: list[str],
    label: str,
    text: str,
    token_budget: int,
    token_estimate: int,
) -> int:
    compact_text = " ".join(text.split()) if "\n" not in text else text.strip()
    part_tokens = _estimate_tokens(compact_text)
    if token_estimate + part_tokens > token_budget:
        return token_estimate
    parts.append(compact_text)
    included.append(label)
    return token_estimate + part_tokens


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}

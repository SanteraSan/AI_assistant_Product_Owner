def normalize_finish_reason(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered in {"stop"}:
        return "stop"
    if lowered in {"length", "max_tokens"}:
        return "length"
    return value

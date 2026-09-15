from app.services.llm.finish_reason import normalize_finish_reason


def test_normalize_finish_reason_maps_stop_and_length() -> None:
    assert normalize_finish_reason("STOP") == "stop"
    assert normalize_finish_reason("stop") == "stop"
    assert normalize_finish_reason("MAX_TOKENS") == "length"
    assert normalize_finish_reason("length") == "length"
    assert normalize_finish_reason("max_tokens") == "length"


def test_normalize_finish_reason_keeps_safety_raw() -> None:
    assert normalize_finish_reason("SAFETY") == "SAFETY"
    assert normalize_finish_reason("content_filter") == "content_filter"


def test_normalize_finish_reason_handles_empty() -> None:
    assert normalize_finish_reason(None) is None
    assert normalize_finish_reason("") is None
    assert normalize_finish_reason("  ") is None

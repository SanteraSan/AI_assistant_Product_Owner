from __future__ import annotations

import logging
import re


# Signed forms only, in this order: JSON keys, api-key headers,
# authorization, then a standalone Bearer token.
_JSON_KEY = (
    r"provider_api_key|gemini_api_key|openrouter_api_key|x-goog-api-key|x-api-key|api_key"
)
_JSON_SECRET = re.compile(
    rf'(?P<prefix>"(?P<key>{_JSON_KEY})"\s*:\s*")(?P<value>(?:\\.|[^"])*)"'
    rf"|(?P<prefix_sq>'(?P<key_sq>{_JSON_KEY})'\s*:\s*')(?P<value_sq>(?:\\.|[^'])*)'",
    re.IGNORECASE,
)
_HEADER_SECRET = re.compile(
    r"(?<![A-Za-z0-9_-])(?P<name>x-goog-api-key|x-api-key)"
    r"(?P<sep>\s*[:=]\s*['\"]?\s*)"
    r"(?P<token>[A-Za-z0-9_\-./+=]+)",
    re.IGNORECASE,
)
_AUTH_SECRET = re.compile(
    r"(?<![A-Za-z0-9_])(?P<name>authorization)"
    r"(?P<sep>['\"]?\s*[:=]\s*['\"]?\s*)"
    r"(?P<bearer>bearer\s+)?"
    r"(?P<token>(?!bearer\b)[A-Za-z0-9_\-./+=]+)",
    re.IGNORECASE,
)
_BEARER_SECRET = re.compile(
    r"(?<![A-Za-z0-9_])(?P<prefix>bearer\s+)(?P<token>[A-Za-z0-9_\-./+=]{8,})",
    re.IGNORECASE,
)
_LOGGER_NAMES = (
    "",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
    "httpcore",
    "app",
)


def redact_secrets(value: str) -> str:
    redacted = _JSON_SECRET.sub(_replace_json_secret, value)
    redacted = _HEADER_SECRET.sub(_replace_header_secret, redacted)
    redacted = _AUTH_SECRET.sub(_replace_auth_secret, redacted)
    return _BEARER_SECRET.sub(_replace_bearer_secret, redacted)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered: str | None = record.getMessage()
        except Exception:
            rendered = None
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_log_value(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact_log_value(item) for key, item in record.args.items()}
        if rendered is not None:
            safe_rendered = redact_secrets(rendered)
            try:
                current = record.getMessage()
            except Exception:
                current = None
            if current != safe_rendered:
                record.msg = safe_rendered
                record.args = ()
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact_secrets(formatted)
            record.exc_info = None
        elif isinstance(record.exc_text, str):
            record.exc_text = redact_secrets(record.exc_text)
        return True


def install_secret_redaction_filter() -> None:
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        _attach_redaction_filter(logger)
        for handler in logger.handlers:
            _attach_redaction_filter(handler)


def _replace_json_secret(match: re.Match[str]) -> str:
    if match.group("prefix") is not None:
        return f'{match.group("prefix")}***"'
    return f"{match.group('prefix_sq')}***'"


def _replace_header_secret(match: re.Match[str]) -> str:
    return f"{match.group('name')}{match.group('sep')}***"


def _replace_auth_secret(match: re.Match[str]) -> str:
    bearer = match.group("bearer") or ""
    return f"{match.group('name')}{match.group('sep')}{bearer}***"


def _replace_bearer_secret(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}***"


def _attach_redaction_filter(target: logging.Filterer) -> None:
    if any(isinstance(item, SecretRedactionFilter) for item in target.filters):
        return
    target.addFilter(SecretRedactionFilter())


def _redact_log_value(value: object) -> object:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: _redact_log_value(item) for key, item in value.items()}
    return value

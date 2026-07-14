from __future__ import annotations

from fastapi import HTTPException, Request


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-CSRF-Token"


def require_csrf(request: Request, *, session_csrf_token: str) -> None:
    if request.method.upper() in SAFE_METHODS:
        return
    header_token = (request.headers.get(CSRF_HEADER) or "").strip()
    if not header_token or header_token != session_csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid.")

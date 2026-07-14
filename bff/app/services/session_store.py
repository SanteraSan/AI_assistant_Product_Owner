from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from redis.asyncio import Redis

from app.services.security import generate_csrf_token, generate_session_id
from app.services.service_jwt import AuthenticatedUser, user_from_dict, user_to_dict


@dataclass
class LoginState:
    state: str
    code_verifier: str
    return_to: str


@dataclass
class UserSession:
    session_id: str
    user: AuthenticatedUser
    csrf_token: str
    access_token: str
    refresh_token: str | None
    id_token: str | None


class SessionStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def save_login_state(self, login_state: LoginState) -> None:
        await self._redis.setex(
            _login_key(login_state.state),
            600,
            json.dumps(asdict(login_state)),
        )

    async def pop_login_state(self, state: str) -> LoginState | None:
        key = _login_key(state)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        await self._redis.delete(key)
        payload = json.loads(raw)
        return LoginState(
            state=str(payload["state"]),
            code_verifier=str(payload["code_verifier"]),
            return_to=str(payload.get("return_to") or "/"),
        )

    async def create_session(
        self,
        *,
        user: AuthenticatedUser,
        access_token: str,
        refresh_token: str | None,
        id_token: str | None,
    ) -> UserSession:
        session = UserSession(
            session_id=generate_session_id(),
            user=user,
            csrf_token=generate_csrf_token(),
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=id_token,
        )
        await self._redis.setex(
            _session_key(session.session_id),
            self._ttl_seconds,
            json.dumps(_session_to_payload(session)),
        )
        return session

    async def get_session(self, session_id: str) -> UserSession | None:
        raw = await self._redis.get(_session_key(session_id))
        if raw is None:
            return None
        return _session_from_payload(json.loads(raw))

    async def delete_session(self, session_id: str) -> UserSession | None:
        key = _session_key(session_id)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        await self._redis.delete(key)
        return _session_from_payload(json.loads(raw))


def _login_key(state: str) -> str:
    return f"bff:login:{state}"


def _session_key(session_id: str) -> str:
    return f"bff:session:{session_id}"


def _session_to_payload(session: UserSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "user": user_to_dict(session.user),
        "csrf_token": session.csrf_token,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "id_token": session.id_token,
    }


def _session_from_payload(payload: dict[str, Any]) -> UserSession:
    return UserSession(
        session_id=str(payload["session_id"]),
        user=user_from_dict(payload.get("user") or {}),
        csrf_token=str(payload.get("csrf_token") or ""),
        access_token=str(payload.get("access_token") or ""),
        refresh_token=(str(payload["refresh_token"]) if payload.get("refresh_token") else None),
        id_token=(str(payload["id_token"]) if payload.get("id_token") else None),
    )

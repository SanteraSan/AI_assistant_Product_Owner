from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ChatMessage, ChatSession


@dataclass(frozen=True)
class ChatExchangeRecord:
    session_id: str
    user_message_id: str
    assistant_message_id: str


@dataclass(frozen=True)
class ChatHistoryMessage:
    role: str
    content: str


class ChatHistoryService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def save_exchange(
        self,
        *,
        session_id: str | None,
        tenant_id: str | None,
        user_id: str | None,
        user_message: str,
        assistant_message: str,
        model: str,
        provider: str,
        latency_ms: int,
        metadata: dict[str, object] | None = None,
    ) -> ChatExchangeRecord:
        async with self._session_factory() as session:
            chat_session = await self._get_or_create_session(
                session=session,
                session_id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                title=user_message,
                metadata=metadata or {},
            )
            _apply_session_context(chat_session, metadata or {})
            created_at = datetime.now(UTC)
            user_entry = ChatMessage(
                session_id=chat_session.id,
                role="user",
                content=user_message,
                metadata_json=metadata or {},
                created_at=created_at,
            )
            assistant_entry = ChatMessage(
                session_id=chat_session.id,
                role="assistant",
                content=assistant_message,
                model=model,
                provider=provider,
                latency_ms=latency_ms,
                metadata_json=metadata or {},
                created_at=created_at + timedelta(milliseconds=1),
            )
            session.add_all([user_entry, assistant_entry])
            await session.commit()

            return ChatExchangeRecord(
                session_id=chat_session.id,
                user_message_id=user_entry.id,
                assistant_message_id=assistant_entry.id,
            )

    async def save_attachment_message(
        self,
        *,
        tenant_id: str,
        user_id: str | None,
        session_id: str | None,
        document_id: str,
        file_name: str,
        source_type: str,
        status: str,
        active_bucket_id: str | None = None,
        model_id: str | None = None,
        approach: str | None = None,
    ) -> ChatMessage | None:
        async with self._session_factory() as session:
            if session_id:
                chat_session = await self._session_for_user(
                    session=session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                )
                if chat_session is None:
                    return None
            else:
                chat_session = await self._get_or_create_session(
                    session=session,
                    session_id=None,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    title=file_name,
                    metadata={},
                )

            if active_bucket_id is not None:
                chat_session.active_bucket_id = _empty_to_none(active_bucket_id)
            if model_id is not None:
                chat_session.model_id = _empty_to_none(model_id)
            if approach is not None:
                chat_session.approach = _empty_to_none(approach)

            attached_document_ids = _metadata_string_list(
                chat_session.metadata_json,
                "attached_document_ids",
            )
            if document_id not in attached_document_ids:
                attached_document_ids.append(document_id)
            chat_session.metadata_json = {
                **(chat_session.metadata_json or {}),
                "attached_document_ids": attached_document_ids,
                "active_document_id": document_id,
            }
            if not chat_session.title or chat_session.title in {"Новый чат", "Untitled chat"}:
                chat_session.title = _build_title(file_name)

            message = ChatMessage(
                session_id=chat_session.id,
                role="user",
                content=f"Прикреплён файл: {file_name}",
                metadata_json={
                    "attachments": [
                        {
                            "id": document_id,
                            "file_name": file_name,
                            "source_type": source_type,
                            "status": status,
                        }
                    ]
                },
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return message

    async def get_recent_messages(
        self,
        *,
        session_id: str | None,
        limit: int = 4,
    ) -> list[ChatHistoryMessage]:
        if not session_id:
            return []

        async with self._session_factory() as session:
            result = await session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(
                    desc(ChatMessage.created_at),
                    # Within the same timestamp, fetch assistant before user so
                    # reverse() restores stable user -> assistant order.
                    _message_role_rank(reverse=True),
                    desc(ChatMessage.id),
                )
                .limit(limit)
            )
            messages = [
                ChatHistoryMessage(
                    role=message.role,
                    content=message.content,
                )
                for message in result.scalars()
            ]
        return list(reversed(messages))

    async def create_session(
        self,
        *,
        tenant_id: str,
        user_id: str | None,
        title: str | None,
        active_bucket_id: str | None,
        model_id: str | None,
        approach: str | None,
        metadata: dict[str, object] | None = None,
    ) -> ChatSession:
        async with self._session_factory() as session:
            chat_session = ChatSession(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                title=_build_title(title or "Новый чат"),
                active_bucket_id=_empty_to_none(active_bucket_id),
                model_id=_empty_to_none(model_id),
                approach=_empty_to_none(approach),
                metadata_json=metadata or {},
            )
            session.add(chat_session)
            await session.commit()
            await session.refresh(chat_session)
            return chat_session

    async def list_sessions(
        self,
        *,
        tenant_id: str,
        user_id: str | None,
        limit: int = 50,
    ) -> list[ChatSession]:
        async with self._session_factory() as session:
            statement = (
                select(ChatSession)
                .where(ChatSession.tenant_id == tenant_id)
                .order_by(desc(ChatSession.updated_at))
                .limit(limit)
            )
            if user_id is not None:
                statement = statement.where(ChatSession.owner_user_id == user_id)
            result = await session.execute(statement)
            return list(result.scalars())

    async def list_messages(
        self,
        *,
        tenant_id: str,
        user_id: str | None,
        session_id: str,
    ) -> list[ChatMessage]:
        async with self._session_factory() as session:
            chat_session = await self._session_for_user(
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            if chat_session is None:
                return []
            result = await session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(
                    ChatMessage.created_at.asc(),
                    _message_role_rank(reverse=False),
                    ChatMessage.id.asc(),
                )
            )
            return list(result.scalars())

    async def delete_session(
        self,
        *,
        tenant_id: str,
        user_id: str | None,
        session_id: str,
    ) -> bool:
        async with self._session_factory() as session:
            chat_session = await self._session_for_user(
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            if chat_session is None:
                return False
            await session.delete(chat_session)
            await session.commit()
            return True

    async def update_session(
        self,
        *,
        tenant_id: str,
        user_id: str | None,
        session_id: str,
        title: str | None = None,
        active_bucket_id: str | None = None,
        model_id: str | None = None,
        approach: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatSession | None:
        async with self._session_factory() as session:
            chat_session = await self._session_for_user(
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            if chat_session is None:
                return None
            if title is not None:
                chat_session.title = _build_title(title)
            if active_bucket_id is not None:
                chat_session.active_bucket_id = _empty_to_none(active_bucket_id)
            if model_id is not None:
                chat_session.model_id = _empty_to_none(model_id)
            if approach is not None:
                chat_session.approach = _empty_to_none(approach)
            if metadata is not None:
                chat_session.metadata_json = {
                    **(chat_session.metadata_json or {}),
                    **metadata,
                }
            await session.commit()
            await session.refresh(chat_session)
            return chat_session

    async def get_session_metadata(
        self,
        *,
        tenant_id: str,
        user_id: str | None,
        session_id: str | None,
    ) -> dict[str, object]:
        if not session_id:
            return {}
        async with self._session_factory() as session:
            chat_session = await self._session_for_user(
                session=session,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            if chat_session is None:
                return {}
            return dict(chat_session.metadata_json or {})

    async def _get_or_create_session(
        self,
        *,
        session: AsyncSession,
        session_id: str | None,
        tenant_id: str | None,
        user_id: str | None,
        title: str,
        metadata: dict[str, object],
    ) -> ChatSession:
        if session_id:
            existing_session = await session.scalar(
                select(ChatSession).where(ChatSession.id == session_id)
            )
            if existing_session is not None:
                if tenant_id and existing_session.tenant_id is None:
                    existing_session.tenant_id = tenant_id
                if user_id and existing_session.owner_user_id is None:
                    existing_session.owner_user_id = user_id
                return existing_session

        session_data = {
            "tenant_id": tenant_id,
            "owner_user_id": user_id,
            "title": _build_title(title),
            "metadata_json": metadata,
        }
        if session_id is not None:
            session_data["id"] = session_id
        chat_session = ChatSession(**session_data)
        session.add(chat_session)
        await session.flush()
        return chat_session

    async def _session_for_user(
        self,
        *,
        session: AsyncSession,
        tenant_id: str,
        user_id: str | None,
        session_id: str,
    ) -> ChatSession | None:
        statement = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == tenant_id,
        )
        if user_id is not None:
            statement = statement.where(ChatSession.owner_user_id == user_id)
        return await session.scalar(statement)


def _message_role_rank(*, reverse: bool):
    # Keep user messages before assistant when timestamps collide.
    user_rank = 1 if reverse else 0
    assistant_rank = 0 if reverse else 1
    return case(
        (ChatMessage.role == "user", user_rank),
        (ChatMessage.role == "assistant", assistant_rank),
        else_=2,
    )


def _build_title(message: str, limit: int = 120) -> str:
    compact = " ".join(message.split())
    return compact[:limit] or "Untitled chat"


def _empty_to_none(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _metadata_string_list(metadata: dict[str, object] | None, key: str) -> list[str]:
    raw_values = (metadata or {}).get(key)
    if not isinstance(raw_values, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        values.append(cleaned)
    return values


def _apply_session_context(chat_session: ChatSession, metadata: dict[str, object]) -> None:
    model_id = _empty_to_none(str(metadata.get("model_id") or ""))
    approach = _empty_to_none(str(metadata.get("approach") or ""))
    active_bucket_id = metadata.get("active_bucket_id")
    bucket_ids = metadata.get("bucket_ids")
    if model_id:
        chat_session.model_id = model_id
    if approach:
        chat_session.approach = approach
    if isinstance(active_bucket_id, str):
        chat_session.active_bucket_id = _empty_to_none(active_bucket_id)
    chat_session.metadata_json = {
        **(chat_session.metadata_json or {}),
        "last_context": {
            "active_bucket_id": active_bucket_id if isinstance(active_bucket_id, str) else None,
            "bucket_ids": bucket_ids if isinstance(bucket_ids, list) else [],
            "document_ids": metadata.get("document_ids") if isinstance(metadata.get("document_ids"), list) else [],
        },
    }

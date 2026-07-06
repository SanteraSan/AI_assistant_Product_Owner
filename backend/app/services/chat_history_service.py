from dataclasses import dataclass

from sqlalchemy import desc, select
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
                title=user_message,
            )
            user_entry = ChatMessage(
                session_id=chat_session.id,
                role="user",
                content=user_message,
                metadata_json=metadata or {},
            )
            assistant_entry = ChatMessage(
                session_id=chat_session.id,
                role="assistant",
                content=assistant_message,
                model=model,
                provider=provider,
                latency_ms=latency_ms,
                metadata_json=metadata or {},
            )
            session.add_all([user_entry, assistant_entry])
            await session.commit()

            return ChatExchangeRecord(
                session_id=chat_session.id,
                user_message_id=user_entry.id,
                assistant_message_id=assistant_entry.id,
            )

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
                .order_by(desc(ChatMessage.created_at))
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

    async def _get_or_create_session(
        self,
        *,
        session: AsyncSession,
        session_id: str | None,
        title: str,
    ) -> ChatSession:
        if session_id:
            existing_session = await session.scalar(
                select(ChatSession).where(ChatSession.id == session_id)
            )
            if existing_session is not None:
                return existing_session

        session_data = {"title": _build_title(title)}
        if session_id is not None:
            session_data["id"] = session_id
        chat_session = ChatSession(**session_data)
        session.add(chat_session)
        await session.flush()
        return chat_session


def _build_title(message: str, limit: int = 120) -> str:
    compact = " ".join(message.split())
    return compact[:limit] or "Untitled chat"

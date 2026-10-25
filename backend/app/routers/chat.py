from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.db.models import ChatMessage, ChatSession
from app.dependencies.auth import get_current_user
from app.models.chat import (
    ChatAttachmentCreateRequest,
    ChatMessageResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
    ChatSessionUpdateRequest,
)
from app.services.access_policy import UserContext
from app.services.chat_history_service import ChatHistoryService


router = APIRouter(tags=["chat"])
chat_history_service: ChatHistoryService


def create_chat_router(*, history_service: ChatHistoryService) -> APIRouter:
    global chat_history_service
    chat_history_service = history_service
    return router


def _chat_session_response(session: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=session.id,
        title=session.title or "Untitled chat",
        tenant_id=session.tenant_id,
        owner_user_id=session.owner_user_id,
        active_bucket_id=session.active_bucket_id,
        model_id=session.model_id,
        approach=session.approach,
        metadata=session.metadata_json or {},
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


def _chat_message_response(message: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        model=message.model,
        provider=message.provider,
        latency_ms=message.latency_ms,
        metadata=message.metadata_json or {},
        created_at=message.created_at.isoformat(),
    )


@router.get("/chat/sessions", response_model=list[ChatSessionResponse])
async def list_chat_sessions(
    user: UserContext = Depends(get_current_user),
) -> list[ChatSessionResponse]:
    sessions = await chat_history_service.list_sessions(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
    )
    return [_chat_session_response(session) for session in sessions]


@router.post("/chat/sessions", response_model=ChatSessionResponse, status_code=201)
async def create_chat_session(
    payload: ChatSessionCreateRequest,
    user: UserContext = Depends(get_current_user),
) -> ChatSessionResponse:
    session = await chat_history_service.create_session(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        title=payload.title,
        active_bucket_id=payload.active_bucket_id,
        model_id=payload.model_id,
        approach=payload.approach,
        metadata=payload.metadata,
    )
    return _chat_session_response(session)


@router.patch("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_chat_session(
    session_id: str,
    payload: ChatSessionUpdateRequest,
    user: UserContext = Depends(get_current_user),
) -> ChatSessionResponse:
    session = await chat_history_service.update_session(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        session_id=session_id,
        title=payload.title,
        active_bucket_id=payload.active_bucket_id,
        model_id=payload.model_id,
        approach=payload.approach,
        metadata=payload.metadata,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return _chat_session_response(session)


@router.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_chat_session(
    session_id: str,
    user: UserContext = Depends(get_current_user),
) -> None:
    deleted = await chat_history_service.delete_session(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        session_id=session_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found.")


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def list_chat_session_messages(
    session_id: str,
    user: UserContext = Depends(get_current_user),
) -> list[ChatMessageResponse]:
    messages = await chat_history_service.list_messages(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        session_id=session_id,
    )
    return [_chat_message_response(message) for message in messages]


@router.post(
    "/chat/sessions/{session_id}/attachments",
    response_model=ChatMessageResponse,
    status_code=201,
)
async def create_chat_attachment_message(
    session_id: str,
    payload: ChatAttachmentCreateRequest,
    user: UserContext = Depends(get_current_user),
) -> ChatMessageResponse:
    message = await chat_history_service.save_attachment_message(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        session_id=session_id,
        document_id=payload.document_id,
        file_name=payload.file_name,
        source_type=payload.source_type,
        status=payload.status,
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return _chat_message_response(message)

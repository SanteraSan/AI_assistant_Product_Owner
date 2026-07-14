import { apiRequest } from '../../shared/api/httpClient'
import type { ChatMessage, ChatThread } from './model'

type RagSourceDto = {
  id: string
  content: string
  score?: number | null
  title?: string | null
  source_type?: string | null
  source_path?: string | null
  metadata?: Record<string, unknown>
}

type RagChatDto = {
  model: string
  response: string
  latency_ms: number
  session_id?: string | null
  assistant_message_id?: string | null
  sources: RagSourceDto[]
}

type ChatSessionDto = {
  id: string
  title: string
  tenant_id?: string | null
  owner_user_id?: string | null
  active_bucket_id?: string | null
  model_id?: string | null
  approach?: string | null
  metadata?: Record<string, unknown>
  created_at: string
  updated_at: string
}

type ChatMessageDto = {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  model?: string | null
  provider?: string | null
  latency_ms?: number | null
  metadata?: Record<string, unknown>
  created_at: string
}

export type SendRagMessagePayload = {
  message: string
  model?: string
  approach?: string
  activeBucketId?: string
  sessionId?: string
  tenantId: string
  bucketIds: string[]
  documentIds: string[]
}

export type CreateChatSessionPayload = {
  title?: string
  activeBucketId?: string
  modelId?: string
  approach?: string
}

export type UpdateChatSessionPayload = CreateChatSessionPayload & {
  title?: string
}

export async function fetchChatSessions(): Promise<ChatThread[]> {
  const sessions = await apiRequest<ChatSessionDto[]>('/api/chat/sessions')
  return sessions.map(chatThreadFromDto)
}

export async function createChatSession(
  payload: CreateChatSessionPayload = {},
): Promise<ChatThread> {
  const session = await apiRequest<ChatSessionDto>('/api/chat/sessions', {
    body: JSON.stringify({
      title: payload.title ?? 'Новый чат',
      active_bucket_id: payload.activeBucketId || null,
      model_id: payload.modelId || null,
      approach: payload.approach || null
  }),
    method: 'POST'
  })
  return chatThreadFromDto(session)
}

export async function updateChatSession(
  sessionId: string,
  payload: UpdateChatSessionPayload,
): Promise<ChatThread> {
  const session = await apiRequest<ChatSessionDto>(`/api/chat/sessions/${sessionId}`, {
    body: JSON.stringify({
      title: payload.title,
      active_bucket_id: payload.activeBucketId ?? null,
      model_id: payload.modelId ?? null,
      approach: payload.approach ?? null
  }),
    method: 'PATCH'
  })
  return chatThreadFromDto(session)
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await apiRequest<void>(`/api/chat/sessions/${sessionId}`, {
    method: 'DELETE'
  })
}

export async function fetchChatMessages(
  sessionId: string,
): Promise<ChatMessage[]> {
  const messages = await apiRequest<ChatMessageDto[]>(`/api/chat/sessions/${sessionId}/messages`)
  return messages.map(chatMessageFromDto)
}

export async function saveChatAttachmentMessage(
  sessionId: string,
  attachment: {
    documentId: string
    fileName: string
    sourceType: string
    status: string
  },
): Promise<ChatMessage> {
  const message = await apiRequest<ChatMessageDto>(`/api/chat/sessions/${sessionId}/attachments`, {
    body: JSON.stringify({
      document_id: attachment.documentId,
      file_name: attachment.fileName,
      source_type: attachment.sourceType,
      status: attachment.status
  }),
    method: 'POST'
  })
  return chatMessageFromDto(message)
}

export async function sendRagMessage(
  payload: SendRagMessagePayload,
): Promise<{
  message: ChatMessage
  sessionId?: string
}> {
  const response = await apiRequest<RagChatDto>('/api/rag/chat', {
    body: JSON.stringify({
      message: payload.message,
      model: payload.model,
      approach: payload.approach,
      active_bucket_id: payload.activeBucketId ?? null,
      session_id: payload.sessionId,
      tenant_id: payload.tenantId,
      bucket_ids: payload.bucketIds,
      document_ids: payload.documentIds
  }),
    method: 'POST'
  })

  return {
    message: {
      id: response.assistant_message_id ?? `assistant-${Date.now()}`,
      role: 'assistant',
      content: response.response,
      sources: response.sources.map((source) => ({
        id: source.id,
        title: source.title ?? source.source_path ?? 'Источник',
        sourceType: source.source_type ?? 'unknown'
  }))
  },
    sessionId: response.session_id ?? undefined
  }
}

function chatThreadFromDto(session: ChatSessionDto): ChatThread {
  const attachedDocumentIds = Array.isArray(session.metadata?.attached_document_ids)
    ? session.metadata.attached_document_ids.filter((value): value is string => typeof value === 'string')
    : []
  return {
    id: session.id,
    title: session.title || 'Новый чат',
    updatedAt: formatRelativeDate(session.updated_at),
    bucketId: session.active_bucket_id ?? '',
    sessionId: session.id,
    bucketIds: session.active_bucket_id ? [session.active_bucket_id] : [],
    documentIds: attachedDocumentIds,
    modelId: session.model_id ?? undefined,
    approach: session.approach ?? undefined
  }
}

function chatMessageFromDto(message: ChatMessageDto): ChatMessage {
  const sources = Array.isArray(message.metadata?.sources)
    ? message.metadata.sources
    : []
  const attachments = Array.isArray(message.metadata?.attachments)
    ? message.metadata.attachments
    : []
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    attachments: attachments
      .filter((attachment): attachment is Record<string, unknown> => typeof attachment === 'object' && attachment !== null)
      .map((attachment) => ({
        id: String(attachment.id ?? ''),
        fileName: String(attachment.file_name ?? attachment.fileName ?? 'file'),
        sourceType: String(attachment.source_type ?? attachment.sourceType ?? 'unknown'),
        status: normalizeAttachmentStatus(attachment.status)
  }))
      .filter((attachment) => attachment.id),
    sources: sources
      .filter((source): source is Record<string, unknown> => typeof source === 'object' && source !== null)
      .map((source) => ({
        id: String(source.id ?? source.qdrant_point_id ?? crypto.randomUUID()),
        title: String(source.title ?? source.source_path ?? 'Источник'),
        sourceType: String(source.source_type ?? 'unknown')
  }))
  }
}

function normalizeAttachmentStatus(
  value: unknown,
): 'uploaded' | 'indexing' | 'indexed' | 'index_failed' | 'error' {
  if (
    value === 'uploaded' ||
    value === 'indexing' ||
    value === 'indexed' ||
    value === 'index_failed' ||
    value === 'error'
  ) {
    return value
  }
  return 'indexing'
}

function formatRelativeDate(value: string): string {
  const timestamp = Date.parse(value)
  if (Number.isNaN(timestamp)) {
    return 'Недавно'
  }
  const diffMs = Date.now() - timestamp
  if (diffMs < 60_000) {
    return 'Только что'
  }
  if (diffMs < 3_600_000) {
    return `${Math.max(1, Math.floor(diffMs / 60_000))} мин. назад`
  }
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    month: '2-digit'
  }).format(timestamp)
}

import { afterEach, describe, expect, it, vi } from 'vitest'
import { createChatSession, sendAgentMessage, sendRagMessage } from '../../entities/chat/api'
import { providerApiKeyForRagRequest } from './providerApiKey'

const QUESTION = 'Сколько открытых багов за неделю?'
const BROWSER_KEY = 'tf-stage5-browser-key'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

const ragDto = {
  model: 'gemini-2.5-flash',
  response: 'Семь критичных багов в отчёте.',
  latency_ms: 1,
  assistant_message_id: 'assistant-1',
  session_id: 'session-1',
  sources: [],
}

const agentDto = {
  model: 'qwen3.5:9b',
  response: 'Семь критичных багов в отчёте.',
  latency_ms: 1,
  assistant_message_id: 'assistant-2',
  session_id: 'session-1',
  sources: [],
  tool_calls: [],
}

const sessionDto = {
  id: 'session-1',
  title: 'Новый чат',
  created_at: '2026-10-25T00:00:00Z',
  updated_at: '2026-10-25T00:00:00Z',
}

describe('providerApiKeyForRagRequest', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns a trimmed key only for external RAG', () => {
    expect(providerApiKeyForRagRequest('external', 'rag', `  ${BROWSER_KEY}  `)).toBe(BROWSER_KEY)
    expect(providerApiKeyForRagRequest('hybrid', 'rag', BROWSER_KEY)).toBeUndefined()
    expect(providerApiKeyForRagRequest('local_only', 'rag', BROWSER_KEY)).toBeUndefined()
    expect(providerApiKeyForRagRequest('external', 'agent', BROWSER_KEY)).toBeUndefined()
    expect(providerApiKeyForRagRequest('external', 'rag', '   ')).toBeUndefined()
  })

  it('adds provider_api_key to the RAG JSON only for that trimmed key', async () => {
    const bodies: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      bodies.push(init?.body ? JSON.parse(String(init.body)) : null)
      return jsonResponse(ragDto)
    }))

    const included = providerApiKeyForRagRequest('external', 'rag', `  ${BROWSER_KEY}  `)
    await sendRagMessage({
      message: QUESTION,
      model: 'gemini-2.5-flash',
      approach: 'external',
      tenantId: 'local_demo',
      bucketIds: ['bucket-1'],
      documentIds: [],
      providerApiKey: included,
    })
    expect(bodies[0]).toMatchObject({ provider_api_key: BROWSER_KEY })

    for (const stored of [providerApiKeyForRagRequest('hybrid', 'rag', BROWSER_KEY), providerApiKeyForRagRequest('local_only', 'rag', BROWSER_KEY), providerApiKeyForRagRequest('external', 'rag', '   ')]) {
      await sendRagMessage({
        message: QUESTION,
        model: 'qwen3.5:9b',
        approach: 'hybrid',
        tenantId: 'local_demo',
        bucketIds: ['bucket-1'],
        documentIds: [],
        providerApiKey: stored,
      })
    }
    expect(bodies.slice(1)).toHaveLength(3)
    for (const body of bodies.slice(1)) {
      expect(body).not.toHaveProperty('provider_api_key')
    }
  })

  it('omits the key from agent and session JSON', async () => {
    const bodies: Array<{ url: string; body: Record<string, unknown> }> = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const target = String(url)
      bodies.push({
        url: target,
        body: init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {},
      })
      if (target.includes('/api/agent/chat')) {
        return jsonResponse(agentDto)
      }
      return jsonResponse(sessionDto)
    }))

    await sendAgentMessage({
      message: QUESTION,
      model: 'qwen3.5:9b',
      approach: 'external',
      tenantId: 'local_demo',
      bucketIds: ['bucket-1'],
      documentIds: [],
    })
    await createChatSession({ title: 'Новый чат', approach: 'external', modelId: 'gemini-2.5-flash' })
    expect(bodies.map((item) => item.url).some((url) => url.includes('/api/agent/chat'))).toBe(true)
    expect(bodies.map((item) => item.url).some((url) => url.includes('/api/chat/sessions'))).toBe(true)
    for (const item of bodies) {
      expect(item.body).not.toHaveProperty('provider_api_key')
    }
  })
})

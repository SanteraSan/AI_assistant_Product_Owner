export type ChatContextDocument = {
  id: string
  fileName: string
  title: string
  status: string
}

export type ChatContextAttachment = {
  id: string
  status: string
}

export type ResolveChatContextInput = {
  message: string
  selectedBucketId: string
  hasBackendBuckets: boolean
  documents: ChatContextDocument[]
  availableDocuments: ChatContextDocument[]
  attachments: ChatContextAttachment[]
  sessionDocumentIds: string[]
}

export function resolveChatContext(
  input: ResolveChatContextInput,
): { bucketIds: string[]; documentIds: string[] } {
  const explicitDocumentIds = namedDocumentIds(input)
  if (explicitDocumentIds.length) {
    return { bucketIds: [], documentIds: explicitDocumentIds }
  }
  if (input.selectedBucketId && asksSelectedBucketDocuments(input.message)) {
    return { bucketIds: selectedBucketIds(input), documentIds: [] }
  }
  const attachmentDocumentIds = indexedAttachmentDocumentIds(input)
  if (attachmentDocumentIds.length) {
    return { bucketIds: [], documentIds: [attachmentDocumentIds[attachmentDocumentIds.length - 1]] }
  }
  if (asksAllAvailableDocuments(input.message) || !input.selectedBucketId) {
    return { bucketIds: [], documentIds: indexedAvailableDocumentIds(input.availableDocuments) }
  }
  return { bucketIds: selectedBucketIds(input), documentIds: [] }
}

function selectedBucketIds(input: ResolveChatContextInput): string[] {
  if (!input.hasBackendBuckets || !input.selectedBucketId) {
    return []
  }
  return [input.selectedBucketId]
}

function indexedAvailableDocumentIds(documents: ChatContextDocument[]): string[] {
  return Array.from(new Set(
    documents
      .filter((document) => document.status === 'indexed')
      .map((document) => document.id),
  ))
}

function indexedAttachmentDocumentIds(input: ResolveChatContextInput): string[] {
  const fromMessages = input.attachments
    .filter((attachment) => attachment.status === 'indexed')
    .map((attachment) => attachment.id)
  const indexedAvailableIds = new Set(indexedAvailableDocumentIds(input.availableDocuments))
  const fromSession = input.sessionDocumentIds.filter((documentId) =>
    indexedAvailableIds.has(documentId),
  )
  return Array.from(new Set([...fromMessages, ...fromSession]))
}

function namedDocumentIds(input: ResolveChatContextInput): string[] {
  const normalized = normalizeDocumentName(input.message)
  const candidates = input.selectedBucketId
    ? [...input.documents, ...input.availableDocuments]
    : input.availableDocuments
  return Array.from(new Set(
    candidates
      .filter((document) => document.status === 'indexed')
      .filter((document) => {
        return documentNameVariants(document.fileName, document.title).some((variant) =>
          normalized.includes(variant),
        )
      })
      .map((document) => document.id),
  ))
}

function asksSelectedBucketDocuments(message: string): boolean {
  const normalized = message.toLowerCase()
  return (
    normalized.includes('bucket') ||
    normalized.includes('бакет') ||
    normalized.includes('в выбранн') ||
    normalized.includes('в текущ')
  )
}

function asksAllAvailableDocuments(message: string): boolean {
  const normalized = message.toLowerCase()
  return (
    normalized.includes('всем доступ') ||
    normalized.includes('все доступ') ||
    normalized.includes('всех доступ') ||
    normalized.includes('по всем документ') ||
    normalized.includes('all available')
  )
}

function normalizeDocumentName(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '')
    .trim()
}

function documentNameVariants(fileName: string, title: string): string[] {
  const stem = fileName.replace(/\.[^.]+$/, '')
  return Array.from(new Set([
    normalizeDocumentName(fileName),
    normalizeDocumentName(stem),
    normalizeDocumentName(title),
  ].filter(Boolean)))
}

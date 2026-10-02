import { describe, expect, it } from 'vitest'
import { resolveChatContext, type ChatContextDocument } from './resolveChatContext'

const resume: ChatContextDocument = {
  id: 'resume',
  fileName: 'резюме.pdf',
  title: 'Резюме',
  status: 'indexed',
}
const smeta: ChatContextDocument = {
  id: 'smeta',
  fileName: 'smeta-materials-table.png',
  title: 'Смета',
  status: 'indexed',
}

const base = {
  selectedBucketId: 'bucket-1',
  hasBackendBuckets: true,
  documents: [resume],
  availableDocuments: [resume, smeta],
  attachments: [{ id: 'smeta', status: 'indexed' }],
  sessionDocumentIds: ['smeta'],
}

describe('resolveChatContext', () => {
  it('switches to the file named in the question', () => {
    expect(resolveChatContext({ ...base, message: 'что в файле резюме.pdf' }).documentIds).toEqual(['resume'])
  })

  it('does not switch files because of a topic word', () => {
    expect(resolveChatContext({ ...base, message: 'какая сумма в смете' }).documentIds).toEqual(['smeta'])
  })

  it('keeps the last indexed attachment when the question has no file name', () => {
    expect(resolveChatContext({
      ...base,
      attachments: [
        { id: 'resume', status: 'indexed' },
        { id: 'smeta', status: 'indexed' },
      ],
      sessionDocumentIds: [],
      message: 'какой итог',
    }).documentIds).toEqual(['smeta'])
  })

  it('does not narrow the scope when the question asks for all documents and no file is attached', () => {
    expect(resolveChatContext({
      ...base,
      attachments: [],
      sessionDocumentIds: [],
      message: 'ответь по всем документам',
    })).toEqual({
      bucketIds: [],
      documentIds: ['resume', 'smeta'],
    })
  })
})

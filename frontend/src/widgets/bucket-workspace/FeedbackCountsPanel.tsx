import type { JSX } from 'react'
import type { FeedbackCounts } from '../../entities/feedback/model'
import { Notice } from '../../shared/ui'

type FeedbackCountsPanelProps = {
  counts: FeedbackCounts | null
  isLoading: boolean
  error: string | null
}

export function FeedbackCountsPanel({
  counts,
  error,
  isLoading,
}: FeedbackCountsPanelProps): JSX.Element | null {
  if (isLoading) {
    return (
      <section className="shrink-0 border-b border-slate-100 px-6 py-4">
        <FeedbackCountsHeading />
        <p className="mt-3 text-sm text-slate-600">Считаем объём…</p>
      </section>
    )
  }

  if (error !== null) {
    return (
      <section className="shrink-0 border-b border-slate-100 px-6 py-4">
        <FeedbackCountsHeading />
        <Notice className="mt-3">{error}</Notice>
      </section>
    )
  }

  if (counts === null) {
    return null
  }

  return (
    <section className="shrink-0 border-b border-slate-100 px-6 py-4">
      <FeedbackCountsHeading />
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <CountValue label="Шум" value={counts.noise} />
        <CountValue label="Короткие сигналы" value={counts.churnSignal} />
        <CountValue label="Баги" value={counts.bug} />
        <CountValue label="Фичи" value={counts.feature} />
        <CountValue label="Всего" value={counts.total} />
        <div>
          <dt className="text-sm text-slate-500">В индексе</dt>
          <dd className="mt-1 text-lg font-semibold text-slate-950">{counts.indexed}</dd>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Флаг index_in_rag, не число точек в Qdrant.
          </p>
        </div>
      </dl>
    </section>
  )
}

function FeedbackCountsHeading() {
  return (
    <>
      <h3 className="text-sm font-semibold text-slate-950">Объём фидбека</h3>
      <p className="mt-1 text-sm text-slate-500">
        Строки в Postgres по классам. Это не результат замера и не вывод модели.
      </p>
    </>
  )
}

function CountValue({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="mt-1 text-lg font-semibold text-slate-950">{value}</dd>
    </div>
  )
}

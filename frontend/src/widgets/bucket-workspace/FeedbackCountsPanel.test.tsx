import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { FeedbackCounts } from '../../entities/feedback/model'
import { FeedbackCountsPanel } from './FeedbackCountsPanel'

const counts: FeedbackCounts = {
  noise: 350,
  churnSignal: 75,
  bug: 60,
  feature: 15,
  total: 500,
  indexed: 70,
}

describe('FeedbackCountsPanel', () => {
  it('renders numbers supplied by the query', () => {
    render(<FeedbackCountsPanel counts={counts} isLoading={false} error={null} />)

    expect(screen.getByText('350')).toBeInTheDocument()
    expect(screen.getByText('75')).toBeInTheDocument()
    expect(screen.getByText('60')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()
    expect(screen.getByText('500')).toBeInTheDocument()
    expect(screen.getByText('70')).toBeInTheDocument()
    expect(screen.getByText('Шум')).toBeInTheDocument()
    expect(screen.getByText('Короткие сигналы')).toBeInTheDocument()
    expect(screen.getByText('Баги')).toBeInTheDocument()
    expect(screen.getByText('Фичи')).toBeInTheDocument()
    expect(screen.getByText('Всего')).toBeInTheDocument()
    expect(screen.getByText('В индексе')).toBeInTheDocument()
    expect(
      screen.getByText('Строки в Postgres по классам. Это не результат замера и не вывод модели.'),
    ).toBeInTheDocument()
  })

  it('renders zeros without an error', () => {
    render(
      <FeedbackCountsPanel
        counts={{ noise: 0, churnSignal: 0, bug: 0, feature: 0, total: 0, indexed: 0 }}
        isLoading={false}
        error={null}
      />,
    )

    expect(screen.getAllByText('0')).toHaveLength(6)
    expect(screen.queryByText('Не удалось загрузить объём фидбека.')).not.toBeInTheDocument()
  })

  it('does not claim the measurement winner', () => {
    const { container } = render(
      <FeedbackCountsPanel counts={counts} isLoading={false} error={null} />,
    )
    const text = container.textContent ?? ''

    expect(text).not.toContain('H1')
    expect(text).not.toContain('победил')
  })
})

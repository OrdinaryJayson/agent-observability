import type { TimeWindow, TrendPoint } from '../types'

const dayMs = 86400000

function utcDay(date: string) {
  return Math.floor(Date.parse(date) / dayMs)
}

export function trendCalendar(points: TrendPoint[], window: TimeWindow) {
  const first = window.from ? utcDay(window.from) : points.length ? utcDay(points[0].date) : null
  // The upper bound is exclusive. A midnight bound must not add another date.
  const last = window.to
    ? Math.ceil(Date.parse(window.to) / dayMs) - 1
    : points.length ? utcDay(points[points.length - 1].date) : null
  if (first === null || last === null || last < first) return null
  return { first, length: last - first + 1, points: new Map(points.map(point => [point.date, point])) }
}

export function trendDays(calendar: ReturnType<typeof trendCalendar>, offset: number, limit: number) {
  if (!calendar) return []
  const days: TrendPoint[] = []
  for (let i = offset; i < Math.min(calendar.length, offset + limit); i++) {
    const date = new Date((calendar.first + i) * dayMs).toISOString().split('T')[0]
    days.push(calendar.points.get(date) ?? { date, total_runs: 0, success_runs: 0, failed_runs: 0 })
  }
  return days
}

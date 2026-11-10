import type { TimeWindow } from '../types'

const timeFormat = new Intl.DateTimeFormat(undefined, {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
})
const countFormat = new Intl.NumberFormat()
const decimalFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })
const millisecondsFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 })
const percentFormat = new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 2 })

export const timeZone = timeFormat.resolvedOptions().timeZone
export const time = (value: string | null) => value === null ? '—' : timeFormat.format(new Date(value))
export const count = (value: number | null) => value === null ? '—' : countFormat.format(value)
export const ms = (value: number | null) => value === null ? '—' : `${millisecondsFormat.format(value)} ms`
export const percent = (value: number | null) => value === null ? '—' : percentFormat.format(value)
export const decimal = (value: number) => decimalFormat.format(value)

export function utcWindow(from: string, to: string): TimeWindow {
  const start = from ? new Date(from).toISOString() : undefined
  const end = to ? new Date(to).toISOString() : undefined
  if (start && end && start >= end) throw new Error('开始时间必须早于结束时间')
  return { from: start, to: end }
}

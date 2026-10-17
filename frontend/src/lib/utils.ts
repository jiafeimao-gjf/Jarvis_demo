import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: (string | undefined | null | boolean)[]) {
  return twMerge(clsx(inputs))
}

export function formatTime(date: Date | string): string {
  const d = typeof date === 'string' ? new Date(date) : date
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit'
  }).format(d)
}

/**
 * 解析后端 UTC 时间。
 *
 * SQLite `CURRENT_TIMESTAMP` 产出 "YYYY-MM-DD HH:MM:SS"（UTC，但无时区标记），
 * JS 会把这种字符串当成**本地时间**解析，导致显示时间偏离时区（如 UTC+8 差 8 小时）。
 * 这里对无时区标记的值补上 Z，按 UTC 解析。
 */
export function parseUtcDate(value: string | null | undefined): Date {
  if (!value) return new Date()
  // 已带时区标记（Z / +08:00）→ 原样解析
  if (/[zZ]$/.test(value) || /[+-]\d{2}:?\d{2}$/.test(value)) return new Date(value)
  return new Date(value.replace(' ', 'T') + 'Z')
}

/** 完整时间戳：YYYY-MM-DD HH:mm:ss（本地时区）。无效值返回空串。 */
export function formatDateTime(date: Date | string | number | null | undefined): string {
  if (date === null || date === undefined || date === '') return ''
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) return ''

  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    ` ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  )
}

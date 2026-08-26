export function fmtDurationHms(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(Number(sec))) return "—"
  const s = Math.max(0, Math.round(Number(sec)))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(h)}:${pad(m)}:${pad(r)}`
}

export function fmtTs(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function fmtTsShort(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function isoFromLocal(local: string): string | undefined {
  if (!local) return undefined
  const d = new Date(local)
  if (Number.isNaN(d.getTime())) return undefined
  return d.toISOString()
}

export function dateFromIso(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function shiftBoundsIso(
  dateYmd: string,
  startHour: number,
  endHour: number,
  startMinute = 0,
  endMinute = 0
): { from: string; to: string } | null {
  if (!dateYmd) return null
  const [y, m, d] = dateYmd.split("-").map(Number)
  if (!y || !m || !d) return null
  const start = new Date(y, m - 1, d, startHour, startMinute, 0, 0)
  const end = new Date(y, m - 1, d, endHour, endMinute, 0, 0)
  const startMin = startHour * 60 + startMinute
  const endMin = endHour * 60 + endMinute
  if (endMin <= startMin) end.setDate(end.getDate() + 1)
  return { from: start.toISOString(), to: end.toISOString() }
}

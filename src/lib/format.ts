export function formatNumber(n: number, digits = 0) {
  return n.toLocaleString("fr-FR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatTonnage(n: number) {
  return `${formatNumber(n)} t`
}

export function formatClock(date: Date = new Date()) {
  return date.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
}

export function formatShortTime(ms: number) {
  return new Date(ms).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}

export function formatTimeHms(ms: number) {
  return new Date(ms).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
}

/** "00:19:18" style elapsed duration, for Film segment durations. */
export function formatElapsedHms(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

export function formatDurationMin(min: number) {
  if (min < 60) return `${Math.round(min)} min`
  const h = Math.floor(min / 60)
  const m = Math.round(min % 60)
  return `${h} h ${m} min`
}

/** "HH:MM" duration (hours:minutes, zero-padded) used for cycle stages. */
export function formatHm(totalMinutes: number) {
  const total = Math.max(0, Math.round(totalMinutes))
  const h = Math.floor(total / 60)
  const m = total % 60
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`
}

export function timeAgo(ms: number, nowMs?: number) {
  if (!Number.isFinite(ms) || ms <= 0) return "—"
  const diff = Math.max(0, (nowMs ?? Date.now()) - ms)
  const min = Math.floor(diff / 60000)
  if (min < 1) return "à l'instant"
  if (min < 60) return `il y a ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `il y a ${h} h ${min % 60}`
  const d = Math.floor(h / 24)
  return `il y a ${d} j`
}

export function parseSimNowMs(simNowIso?: string | null): number | undefined {
  if (!simNowIso) return undefined
  const ms = Date.parse(simNowIso)
  return Number.isFinite(ms) ? ms : undefined
}

/** Relative age against the operational/simulation clock, never wall-clock by default. */
export function operationalTimeAgo(ms: number, simNowIso?: string | null) {
  return timeAgo(ms, parseSimNowMs(simNowIso))
}

/** Detail timestamp: "01 sept. 2026 · 14:32" */
export function formatOperationalDateTime(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "—"
  const date = new Date(ms)
  if (Number.isNaN(date.getTime())) return "—"
  const day = date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })
  const time = date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", hour12: false })
  return `${day} · ${time}`
}

export function formatOperationalClock(simNowIso?: string | null): string {
  const ms = parseSimNowMs(simNowIso)
  if (ms == null) return "—"
  return formatShortTime(ms)
}

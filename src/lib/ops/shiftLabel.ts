import type { Shift } from "@/lib/mock/types"

export type PosteId = "matin" | "apres-midi" | "nuit"
export type SelectedPoste = "all" | PosteId

export const CANONICAL_POSTES: ReadonlyArray<{ id: PosteId; name: string }> = [
  { id: "matin", name: "Poste matin" },
  { id: "apres-midi", name: "Poste après-midi" },
  { id: "nuit", name: "Poste nuit" },
]

export const POSTE_SELECTOR_OPTIONS: ReadonlyArray<{ id: SelectedPoste; name: string }> = [
  { id: "all", name: "Tous les postes" },
  ...CANONICAL_POSTES,
]

const POSTE_BY_ID = new Map<PosteId, (typeof CANONICAL_POSTES)[number]>(
  CANONICAL_POSTES.map((row) => [row.id, row])
)

const POSTE_MATCHERS: Array<[RegExp, PosteId]> = [
  [/apr[eè]s[- ]?midi|afternoon/i, "apres-midi"],
  [/matin|morning/i, "matin"],
  [/nuit|night/i, "nuit"],
]

export function posteFromShiftName(name: string | null | undefined): PosteId | null {
  const raw = (name ?? "").trim()
  if (!raw) return null
  const stripped = raw.replace(/^poste\s+/i, "")
  for (const [pattern, id] of POSTE_MATCHERS) {
    if (pattern.test(raw) || pattern.test(stripped)) return id
  }
  return null
}

export function canonicalPosteName(id: SelectedPoste): string {
  if (id === "all") return "Tous les postes"
  return POSTE_BY_ID.get(id)?.name ?? "Poste"
}

export function formatPosteName(name: string | null | undefined): string {
  const id = posteFromShiftName(name)
  if (id) return canonicalPosteName(id)
  const raw = (name ?? "").trim()
  return raw || "Poste"
}

const SHORT_LABEL: Record<PosteId, string> = {
  matin: "Matin",
  "apres-midi": "Après-midi",
  nuit: "Nuit",
}

export function canonicalShiftName(name: string | null | undefined): string {
  const id = posteFromShiftName(name)
  if (id) return SHORT_LABEL[id]
  const raw = (name ?? "").trim()
  if (!raw) return "Poste"
  const stripped = raw.replace(/^poste\s+/i, "")
  return stripped.replace(/^./, (ch) => ch.toUpperCase()) || raw
}

export function shiftDateKey(shift: Pick<Shift, "windowStart">): string | null {
  if (!shift.windowStart) return null
  const ms = Date.parse(shift.windowStart)
  if (!Number.isFinite(ms)) return null
  return new Date(ms).toISOString().slice(0, 10)
}

export function formatShiftLabel(shift: Shift, options?: { withDate?: boolean }): string {
  const name = formatPosteName(shift.name)
  if (options?.withDate === false) return name
  const key = shiftDateKey(shift)
  if (!key || !shift.windowStart) return name
  const dateLabel = new Date(shift.windowStart).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
  })
  return `${name} · ${dateLabel}`
}

function shiftRank(shift: Shift): number {
  return shift.databaseId ?? 0
}

/** One row per operational date + canonical shift name. Not used by the operator poste selector. */
export function uniqueShifts(shifts: readonly Shift[], selectedId?: string): Shift[] {
  const order: string[] = []
  const groups = new Map<string, Shift[]>()
  for (const shift of shifts) {
    const key = `${shiftDateKey(shift) ?? "_"}:${canonicalShiftName(shift.name)}`
    if (!groups.has(key)) order.push(key)
    const list = groups.get(key) ?? []
    list.push(shift)
    groups.set(key, list)
  }
  return order.map((key) => {
    const group = groups.get(key) ?? []
    const selected = selectedId ? group.find((row) => row.id === selectedId) : undefined
    if (selected) return selected
    return group.reduce((best, row) => (shiftRank(row) >= shiftRank(best) ? row : best))
  })
}

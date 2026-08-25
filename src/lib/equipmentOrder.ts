/** Stable display order: TRK-2 before TRK-10, prefix groups EXC < LDR < TRK. */

function parseEquipmentCode(code: string): { prefix: string; num: number; raw: string } {
  const m = code.match(/^([A-Za-z]+)-(\d+)$/)
  if (m) return { prefix: m[1].toUpperCase(), num: Number.parseInt(m[2], 10), raw: code }
  return { prefix: code.toUpperCase(), num: Number.POSITIVE_INFINITY, raw: code }
}

const PREFIX_RANK: Record<string, number> = {
  TRK: 0,
  EXC: 1,
  LDR: 2,
}

export function compareEquipmentByCode(a: { code: string }, b: { code: string }): number {
  const pa = parseEquipmentCode(a.code)
  const pb = parseEquipmentCode(b.code)
  const ra = PREFIX_RANK[pa.prefix] ?? 50
  const rb = PREFIX_RANK[pb.prefix] ?? 50
  if (ra !== rb) return ra - rb
  if (pa.num !== pb.num) return pa.num - pb.num
  return pa.raw.localeCompare(pb.raw)
}

export function sortEquipmentByCode<T extends { code: string }>(items: T[]): T[] {
  return [...items].sort(compareEquipmentByCode)
}

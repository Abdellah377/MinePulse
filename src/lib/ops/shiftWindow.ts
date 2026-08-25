import type { Shift } from "@/lib/mock/types"

/** Shift window bounds from simulation clock + shift definition (API mode). */
export function shiftWindowBounds(
  simNowIso: string | null,
  shift: Shift | undefined
): { startMs: number; endMs: number; nowMs: number } {
  const nowMs = simNowIso ? new Date(simNowIso).getTime() : Date.now()
  if (!shift) {
    const d = new Date(nowMs)
    d.setHours(0, 0, 0, 0)
    return { startMs: d.getTime(), endMs: nowMs, nowMs }
  }

  const now = new Date(nowMs)
  const startMinute = shift.startMinute ?? 0
  const endMinute = shift.endMinute ?? 0
  const start = new Date(now)
  start.setHours(shift.startHour, startMinute, 0, 0)
  const end = new Date(now)
  end.setHours(shift.endHour, endMinute, 0, 0)

  const startMin = shift.startHour * 60 + startMinute
  const endMin = shift.endHour * 60 + endMinute
  const nowMin = now.getHours() * 60 + now.getMinutes()

  if (endMin <= startMin) {
    if (nowMin < endMin) {
      start.setDate(start.getDate() - 1)
    } else {
      end.setDate(end.getDate() + 1)
    }
  } else if (nowMs < start.getTime()) {
    start.setDate(start.getDate() - 1)
    end.setDate(end.getDate() - 1)
  }

  return { startMs: start.getTime(), endMs: end.getTime(), nowMs }
}

export function shiftRemainingMinutes(
  simNowIso: string | null,
  shift: Shift | undefined
): number {
  const { endMs, nowMs } = shiftWindowBounds(simNowIso, shift)
  let remaining = Math.round((endMs - nowMs) / 60_000)
  if (remaining < 0) remaining += 24 * 60
  return Math.max(0, remaining)
}

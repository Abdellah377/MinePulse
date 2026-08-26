import { describe, expect, it, vi } from "vitest"
vi.mock("@/lib/api/client", () => ({ useApiMode: false }))

import { shiftWindowBounds } from "./shiftWindow"

describe("shiftWindowBounds minutes", () => {
  it("uses startMinute/endMinute instead of assuming :00", () => {
    const shift = {
      id: "shift-1",
      name: "Matin",
      startHour: 6,
      endHour: 14,
      startMinute: 30,
      endMinute: 15,
    }
    const sim = new Date(Date.UTC(2026, 7, 19, 10, 0, 0))
    const { startMs, endMs } = shiftWindowBounds(sim.toISOString(), shift)
    expect(new Date(startMs).getMinutes()).toBe(30)
    expect(new Date(endMs).getMinutes()).toBe(15)
  })

  it("keeps overnight shift open past endHour when endMinute is later", () => {
    const shift = {
      id: "shift-night",
      name: "Nuit",
      startHour: 22,
      endHour: 6,
      startMinute: 0,
      endMinute: 15,
    }
    const local = new Date(2026, 7, 19, 6, 10, 0, 0)
    const { startMs, endMs, nowMs } = shiftWindowBounds(local.toISOString(), shift)
    expect(nowMs).toBeGreaterThanOrEqual(startMs)
    expect(nowMs).toBeLessThan(endMs)
  })
})

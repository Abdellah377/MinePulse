import { expect, it } from "vitest"
import { newestAlertsFirst, operationalAlertTime } from "./order"

it("orders copied alerts by full operational timestamp across hours without mutating state", () => {
  const oldRun = {
    id: "old",
    occurredAt: new Date("2026-01-29T17:50:00Z").getTime(),
    createdAt: new Date("2026-08-27T18:00:00Z").getTime(),
  }
  const newRun = {
    id: "new",
    occurredAt: new Date("2026-01-30T07:13:00Z").getTime(),
    createdAt: new Date("2026-08-27T17:00:00Z").getTime(),
  }
  const original = [oldRun, newRun]

  const ordered = newestAlertsFirst(original)

  expect(ordered.map((item) => item.id)).toEqual(["new", "old"])
  expect(original.map((item) => item.id)).toEqual(["old", "new"])
  expect(ordered).not.toBe(original)
})

it("uses createdAt only as a documented legacy fallback", () => {
  const legacy = { createdAt: Date.parse("2026-01-29T07:08:00Z") }
  expect(operationalAlertTime(legacy)).toBe(legacy.createdAt)
})

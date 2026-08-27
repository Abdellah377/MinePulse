import { expect, it } from "vitest"
import { newestAlertsFirst } from "./order"

it("orders copied alerts by full timestamp across hours without mutating state", () => {
  const oldRun = { id: "old", createdAt: new Date("2026-01-29T17:50:00Z").getTime() }
  const newRun = { id: "new", createdAt: new Date("2026-01-30T07:13:00Z").getTime() }
  const original = [oldRun, newRun]

  const ordered = newestAlertsFirst(original)

  expect(ordered.map((item) => item.id)).toEqual(["new", "old"])
  expect(original.map((item) => item.id)).toEqual(["old", "new"])
  expect(ordered).not.toBe(original)
})

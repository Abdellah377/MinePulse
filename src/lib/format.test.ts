import { expect, it } from "vitest"

import { formatOperationalDateTime, operationalTimeAgo, timeAgo } from "./format"

it("operationalTimeAgo uses simulation now instead of wall clock", () => {
  const event = Date.parse("2026-01-29T10:00:00.000Z")
  const simNow = "2026-01-29T10:05:00.000Z"
  expect(operationalTimeAgo(event, simNow)).toBe("il y a 5 min")
  expect(timeAgo(event, Date.parse("2026-09-01T10:00:00.000Z"))).toBe("il y a 215 j")
})

it("formatOperationalDateTime keeps date and clock together", () => {
  const label = formatOperationalDateTime(Date.parse("2026-09-01T14:32:00.000Z"))
  expect(label).toContain("2026")
  expect(label).toContain("·")
  expect(label).toMatch(/\d{2}:\d{2}/)
})

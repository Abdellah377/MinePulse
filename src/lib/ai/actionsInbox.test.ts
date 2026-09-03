import { describe, expect, it } from "vitest"

import type { ActionsInboxItem } from "@/lib/api/types/optimization"
import { mergeInboxItems, nextInboxSelection, pickInboxSelection, removeInboxItem } from "./actionsInbox"

const item = (id: string, status: ActionsInboxItem["status"] = "new"): ActionsInboxItem => ({
  id,
  severity: "warning",
  status,
  title: id,
  description: "",
  equipmentId: null,
  zoneId: null,
  location: "Site",
  category: "CONGESTION_RISK",
  createdAt: 1,
  updatedAt: 1,
  assignedTo: null,
  resolution: null,
  hasInvestigation: false,
  investigationId: null,
  hasRecommendation: false,
  optimizationEligible: true,
  eligibility: "OPTIMIZABLE",
  latestRunOutcome: null,
  latestRunId: null,
})

describe("actions inbox helpers", () => {
  it("direct open picks the first active item when nothing is preferred", () => {
    expect(pickInboxSelection([item("alert-1"), item("alert-2")], null)).toBe("alert-1")
    expect(pickInboxSelection([], null)).toBeNull()
  })

  it("deep-link selects the requested id when present", () => {
    expect(pickInboxSelection([item("alert-1"), item("alert-2")], "alert-2")).toBe("alert-2")
  })

  it("falls back to first item when the deep-link is missing from the loaded page", () => {
    expect(pickInboxSelection([item("alert-1")], "alert-99")).toBe("alert-1")
  })

  it("refresh keeps the operator selection even when a newer item is first", () => {
    const items = [item("alert-new"), item("alert-a")]
    expect(nextInboxSelection(items, "alert-a", null)).toBe("alert-a")
    expect(nextInboxSelection(items, "alert-a", "alert-new")).toBe("alert-a")
  })

  it("first load uses pickInboxSelection when nothing is currently selected", () => {
    const items = [item("alert-1"), item("alert-2")]
    expect(nextInboxSelection(items, null, "alert-2")).toBe("alert-2")
    expect(nextInboxSelection(items, null, null)).toBe("alert-1")
  })

  it("explicit context navigation prefers the new context id", () => {
    const items = [item("alert-new"), item("alert-a")]
    expect(nextInboxSelection(items, "alert-a", "alert-new", { explicitContext: true })).toBe("alert-new")
  })

  it("falls back to context then first item only after the current id is gone", () => {
    const items = [item("alert-1"), item("alert-2")]
    expect(nextInboxSelection(items, "alert-gone", "alert-2")).toBe("alert-2")
    expect(nextInboxSelection(items, "alert-gone", "alert-missing")).toBe("alert-1")
    expect(nextInboxSelection([], "alert-gone", null)).toBeNull()
  })

  it("merges load-more pages without duplicate ids", () => {
    const merged = mergeInboxItems([item("alert-1")], [item("alert-1", "acknowledged"), item("alert-2")])
    expect(merged.map((row) => row.id)).toEqual(["alert-1", "alert-2"])
    expect(merged[0].status).toBe("acknowledged")
  })

  it("prepending a deep-linked case keeps it first without duplicating", () => {
    const merged = mergeInboxItems([item("alert-2")], [item("alert-9")], { prepend: true })
    expect(merged.map((row) => row.id)).toEqual(["alert-9", "alert-2"])
  })

  it("resolve removes the item from the active inbox and selects the next", () => {
    const { remaining, nextSelectedId } = removeInboxItem([item("alert-1"), item("alert-2")], "alert-1")
    expect(remaining.map((row) => row.id)).toEqual(["alert-2"])
    expect(nextSelectedId).toBe("alert-2")
    expect(removeInboxItem([item("alert-1")], "alert-1")).toEqual({ remaining: [], nextSelectedId: null })
  })
})

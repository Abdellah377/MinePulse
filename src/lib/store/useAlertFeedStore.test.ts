import { beforeEach, describe, expect, it } from "vitest"

import type { Alert } from "@/lib/mock/types"
import { useAlertFeedStore } from "./useAlertFeedStore"

const alert = (id: string, createdAt: number, status: Alert["status"] = "new"): Alert => ({
  id,
  severity: "warning",
  status,
  title: id,
  description: "",
  equipmentId: "TR-01",
  zoneId: null,
  location: "Site",
  category: "CONGESTION_RISK",
  createdAt,
  updatedAt: createdAt,
  assignedTo: null,
  resolution: null,
})

describe("useAlertFeedStore", () => {
  beforeEach(() => {
    useAlertFeedStore.getState().reset()
  })

  it("prepends new ids without dropping older pages", () => {
    useAlertFeedStore.getState().appendPage({
      items: [alert("alert-2", 2), alert("alert-3", 3)],
      nextCursor: "c2",
      hasMore: true,
      activeCount: 2,
    })
    useAlertFeedStore.getState().mergeHead({
      items: [alert("alert-1", 1), alert("alert-2", 2)],
      nextCursor: "c1",
      hasMore: true,
      activeCount: 3,
    })
    expect(useAlertFeedStore.getState().orderedIds).toEqual(["alert-1", "alert-2", "alert-3"])
    expect(useAlertFeedStore.getState().nextCursor).toBe("c2")
    expect(useAlertFeedStore.getState().activeCount).toBe(3)
  })

  it("dedupes by id and keeps resolved rows", () => {
    useAlertFeedStore.getState().mergeHead({
      items: [alert("alert-1", 1)],
      nextCursor: null,
      hasMore: false,
      activeCount: 1,
    })
    useAlertFeedStore.getState().upsert(alert("alert-1", 1, "resolved"))
    expect(useAlertFeedStore.getState().orderedIds).toEqual(["alert-1"])
    expect(useAlertFeedStore.getState().byId["alert-1"].status).toBe("resolved")
  })

  it("mapping the feed inside a Zustand selector allocates a new array every snapshot", () => {
    useAlertFeedStore.getState().mergeHead({
      items: [alert("alert-1", 1)],
      nextCursor: null,
      hasMore: false,
      activeCount: 1,
    })
    const mapInsideSelector = (s: ReturnType<typeof useAlertFeedStore.getState>) =>
      s.orderedIds.map((id) => s.byId[id]).filter(Boolean)
    const first = mapInsideSelector(useAlertFeedStore.getState())
    const second = mapInsideSelector(useAlertFeedStore.getState())
    expect(first).toEqual(second)
    expect(first).not.toBe(second)
    expect(useAlertFeedStore.getState().orderedIds).toBe(useAlertFeedStore.getState().orderedIds)
    expect(useAlertFeedStore.getState().byId).toBe(useAlertFeedStore.getState().byId)
  })

  it("caps stored ids and does not duplicate on append", () => {
    const rows = Array.from({ length: 12 }, (_, i) => alert(`alert-${i}`, i))
    useAlertFeedStore.getState().appendPage({ items: rows, nextCursor: "c", hasMore: true, activeCount: 12 })
    useAlertFeedStore.getState().appendPage({ items: rows.slice(0, 3), nextCursor: "c2", hasMore: false, activeCount: 12 })
    const ids = useAlertFeedStore.getState().orderedIds
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toHaveLength(12)
  })
})

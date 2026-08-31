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
})

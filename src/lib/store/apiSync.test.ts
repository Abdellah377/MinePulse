import { describe, expect, it } from "vitest"

import {
  connectionAfterEquipmentPoll,
  FULL_HYDRATE_ERROR,
  isFullWorldPayload,
  isStickyClientError,
  nextErrorAfterEquipmentPoll,
  nextErrorAfterFullHydrate,
  pollCatchError,
  shouldStampSuccessfulSync,
} from "./apiSync"

describe("equipment-only poll must not wipe sticky errors", () => {
  it("keeps zone/alert/settings/incomplete errors", () => {
    expect(nextErrorAfterEquipmentPoll("Échec enregistrement zone")).toBe("Échec enregistrement zone")
    expect(nextErrorAfterEquipmentPoll("Échec mise à jour alerte")).toBe("Échec mise à jour alerte")
    expect(nextErrorAfterEquipmentPoll("Impossible de charger les paramètres opérationnels")).toBe(
      "Impossible de charger les paramètres opérationnels"
    )
    expect(nextErrorAfterEquipmentPoll(FULL_HYDRATE_ERROR)).toBe(FULL_HYDRATE_ERROR)
  })

  it("clears a transient poll interrupt only when it is not sticky", () => {
    expect(nextErrorAfterEquipmentPoll("Synchronisation interrompue")).toBeNull()
    expect(nextErrorAfterEquipmentPoll(null)).toBeNull()
  })

  it("does not mark online after equipment poll if full world was never loaded", () => {
    expect(
      connectionAfterEquipmentPoll({ fullWorldHydrated: false, apiPollError: null })
    ).toBe("degraded")
    expect(
      shouldStampSuccessfulSync({ fullWorldHydrated: false, apiPollError: null })
    ).toBe(false)
  })

  it("stays degraded when a mutation error is outstanding even if world is hydrated", () => {
    expect(
      connectionAfterEquipmentPoll({
        fullWorldHydrated: true,
        apiPollError: "Échec enregistrement zone",
      })
    ).toBe("degraded")
  })

  it("can be online after equipment poll only when full hydrate succeeded and no error", () => {
    expect(connectionAfterEquipmentPoll({ fullWorldHydrated: true, apiPollError: null })).toBe("online")
    expect(shouldStampSuccessfulSync({ fullWorldHydrated: true, apiPollError: null })).toBe(true)
  })
})

describe("full hydrate", () => {
  it("requires production + timeline", () => {
    expect(isFullWorldPayload({})).toBe(false)
    expect(isFullWorldPayload({ productionByShift: { hourly: [], daily: [], shiftly: [] } })).toBe(false)
    expect(
      isFullWorldPayload({
        productionByShift: { hourly: [], daily: [], shiftly: [] },
        timelineSegments: [],
      })
    ).toBe(true)
  })

  it("does not clear mutation or settings errors", () => {
    expect(nextErrorAfterFullHydrate("Échec enregistrement zone")).toBe("Échec enregistrement zone")
    expect(nextErrorAfterFullHydrate("Impossible de charger les paramètres opérationnels")).toBe(
      "Impossible de charger les paramètres opérationnels"
    )
    expect(nextErrorAfterFullHydrate(FULL_HYDRATE_ERROR)).toBeNull()
    expect(isStickyClientError(FULL_HYDRATE_ERROR)).toBe(true)
  })
})

describe("poll catch", () => {
  it("does not replace a sticky error with Synchronisation interrompue", () => {
    expect(pollCatchError("Échec suppression zone")).toBe("Échec suppression zone")
    expect(pollCatchError(null)).toBe("Synchronisation interrompue")
  })
})

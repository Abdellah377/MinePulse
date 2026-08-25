import { describe, expect, it, vi } from "vitest"

import { formatEquipmentContribution, equipmentContributionTons } from "./contribution"

vi.mock("@/lib/api/client", () => ({
  useApiMode: true,
}))

const truck = {
  payloadTons: 0,
  capacityTons: 100,
  tripsThisShift: 10,
}

describe("equipment contribution API mode", () => {
  it("does not display capacity * trips * 0.94", () => {
    const fabricated = truck.capacityTons * truck.tripsThisShift * 0.94
    const displayed = formatEquipmentContribution(truck)
    expect(displayed).toBe("—")
    expect(displayed).not.toBe(`${fabricated.toFixed(0)} t`)
    expect(equipmentContributionTons(truck)).toBeNull()
  })
})

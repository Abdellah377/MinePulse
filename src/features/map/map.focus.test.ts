import { expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { mapCameraForEquipment, mapFocusEpoch } from "./map.focus"

it("does not invent a camera when coordinates are missing", () => {
  expect(mapCameraForEquipment({ position: null })).toBeNull()
  expect(mapCameraForEquipment(null)).toBeNull()
  expect(mapFocusEpoch("TRK-010", false)).toBeNull()
})

it("centers on converted workspace coordinates, never [0, 0]", () => {
  const camera = mapCameraForEquipment({ position: { x: 420, y: 280 } })
  expect(camera).not.toBeNull()
  expect(camera!.center).not.toEqual([0, 0])
  expect(camera!.center[0]).not.toBe(0)
  expect(camera!.center[1]).not.toBe(0)
  expect(camera!.zoom).toBe(15.5)
})

it("alert and inspector map actions share the same focus helper", () => {
  const alerts = readFileSync("src/components/ai/InvestigationAlerts.tsx", "utf8")
  const inspector = readFileSync("src/components/equipment/EquipmentDetailContent.tsx", "utf8")
  const carte = readFileSync("src/pages/supervision/Carte.tsx", "utf8")
  expect(alerts).toContain("openMapForTarget")
  expect(inspector).toContain("openMapForTarget")
  expect(carte).toContain("mapCameraForEquipment")
  expect(carte).toContain("mapFocusEpoch")
  expect(carte).toContain("focusRequestId")
})


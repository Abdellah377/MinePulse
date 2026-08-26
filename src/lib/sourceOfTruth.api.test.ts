import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { readFileSync, readdirSync } from "node:fs"
import { join } from "node:path"
import { expect, it, vi } from "vitest"
import { unknownEquipment } from "@/test/aiFixtures"
import { buildRecentTrail, advanceSimulatedPositions } from "@/features/map/map.simulation"
import { equipmentToGeoJSON, fitBoundsFromEquipment } from "@/features/map/map.utils"
import { CycleStepper } from "@/components/parc/CycleStepper"
import { AiSlot } from "@/components/ai/AiSlot"
import { MiniTimelineStrip } from "@/components/equipment/MiniTimelineStrip"
import { OemGrid } from "@/components/oem/OemDataTable"
import { fmtDurationHms } from "@/lib/oem/format"
import { shiftRemainingMinutes, shiftWindowBounds } from "@/lib/ops/shiftWindow"
import { useOpsStore } from "@/lib/store/useOpsStore"

vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("./api/client")>(), useApiMode: true }))

it("API-mode store starts empty and synthetic map movement/trails cannot leak", () => {
  expect(useOpsStore.getInitialState().equipment).toEqual([])
  expect(useOpsStore.getInitialState().alerts).toEqual([])
  expect(useOpsStore.getInitialState().settingsLoaded).toBe(false)
  expect(buildRecentTrail(unknownEquipment, [])).toEqual([])
  expect(advanceSimulatedPositions([unknownEquipment], [], null, 50)).toEqual([unknownEquipment])
})
it("unknown map position, speed, heading and state duration do not turn into zero", () => {
  expect(fitBoundsFromEquipment([unknownEquipment])).toBeNull()
  expect(equipmentToGeoJSON([unknownEquipment], []).features).toEqual([])
  const located = { ...unknownEquipment, position: { x: 20, y: 10 } }
  expect(equipmentToGeoJSON([located], []).features[0].properties).toMatchObject({ speedKmh: null, heading: null, timeInStateMin: null })
})
it("incomplete cycle totals and null connectivity stay unavailable", () => {
  const html = renderToStaticMarkup(createElement(CycleStepper, { stages: [{ key: "vide", minutes: null, isCurrent: false, isOutlier: false }], dureeMoyenneMin: null }))
  expect(html).toContain("Incomplet / non mesuré")
  expect(fmtDurationHms(null)).toBe("—")
  expect(fmtDurationHms(0)).toBe("00:00:00")
  const grid = renderToStaticMarkup(createElement(OemGrid, { columns: [{ id: "alarms", header: "Alarmes", tone: "alarm-red" }], rows: [{ alarms: 0 }, { alarms: null }] }))
  expect(grid).toContain(">0</span>")
  expect(grid).toContain("—")
})
it("legacy AI slots cannot show injected mock confidence or advice in API mode", () => {
  const html = renderToStaticMarkup(createElement(AiSlot, { insight: { title: "fake", body: "fabricated intelligence", confidence: 97, action: "fake optimization" } }))
  expect(html).toContain("non évaluée")
  expect(html).not.toContain("fabricated")
  expect(html).not.toContain("97")
})
it("mini-film keeps gaps instead of moving segments together", () => {
  const html = renderToStaticMarkup(createElement(MiniTimelineStrip, { rangeStart: 0, rangeEnd: 100, segments: [{ id: "s", equipmentId: "unit", state: "eteint", start: 50, end: 60, zoneName: null }] }))
  expect(html).toContain("left:50%")
  expect(html).toContain("width:10%")
})
it("uses the server's dated shift window, including historical shifts and no midnight wrap", () => {
  const shift = { id: "shift-29", name: "historical", startHour: 6, endHour: 14, windowStart: "2026-08-20T06:30:00Z", windowEnd: "2026-08-20T14:15:00Z" }
  expect(shiftWindowBounds("2026-08-26T10:00:00Z", shift).startMs).toBe(Date.parse(shift.windowStart))
  expect(shiftRemainingMinutes("2026-08-26T10:00:00Z", shift)).toBe(0)
  expect(Number.isNaN(shiftWindowBounds(null, undefined).nowMs)).toBe(true)
})
it("changing scope clears previous operational values before loading the next context", () => {
  useOpsStore.setState({ selectedSiteId: "SITE-17", selectedShiftId: "shift-29", equipment: [unknownEquipment], productionByShift: { hourly: [{ label: "10", tonnage: 100, target: null }], daily: [], shiftly: [] } })
  useOpsStore.getState().setSelectedShift("shift-30")
  expect(useOpsStore.getState().equipment).toEqual([])
  expect(useOpsStore.getState().productionByShift.hourly).toEqual([])
  expect(useOpsStore.getState().lastSuccessfulSyncAt).toBeNull()
})

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)])
}
it("production paths do not import simulator internals or simulator API; only the explicit DEV screen may", () => {
  expect(readFileSync("src/App.tsx", "utf8")).toContain('const SimulationCentre = import.meta.env.DEV ?')
  const paths = [...files("src/pages"), ...files("src/components"), ...files("src/features"), ...files("src/lib")]
    .filter((f) => /\.tsx?$/.test(f) && !f.endsWith(".test.ts") && !f.endsWith("SimulationCentre.tsx") && !f.endsWith("simulation.ts"))
  for (const path of paths) {
    const text = readFileSync(path, "utf8")
    expect(text, path).not.toMatch(/(?:from|import\s*\()\s*["'][^"']*(?:backend\/simulator|simulator\.|lib\/api\/simulation)/)
    expect(text, path).not.toMatch(/\bSimWorld\b/)
  }
  for (const path of ["src/components/ai/InvestigationAlerts.tsx", "src/components/ai/InvestigationActions.tsx", "src/lib/api/ai.ts", "src/lib/performance/apiMetrics.ts"]) {
    expect(readFileSync(path, "utf8"), path).not.toMatch(/(?:scenario|generator|dispatchOptimizationBundle|investigateException)/)
  }
})

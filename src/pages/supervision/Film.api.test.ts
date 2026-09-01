import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"
import type { Equipment, Shift, TimelineSegment } from "@/lib/mock/types"
import { unknownEquipment } from "@/test/aiFixtures"
import Film from "./Film"
import { MiniTimelineStrip } from "@/components/equipment/MiniTimelineStrip"

const fixture = vi.hoisted(() => ({
  equipment: [] as Equipment[], timelineSegments: [] as TimelineSegment[],
  analysisTimelineSegments: [] as TimelineSegment[],
  shifts: [] as Shift[], selectedShiftId: "shift-test", simNowIso: null as string | null,
  periodFrom: "2026-01-29", periodTo: "2026-01-29", selectedPoste: "all" as const,
  selectedSiteId: "SITE-A",
  setAnalysisTimeline: (rows: TimelineSegment[]) => { fixture.analysisTimelineSegments = rows },
}))
vi.mock("@/lib/api/client", async (original) => ({
  ...await original<typeof import("@/lib/api/client")>(), useApiMode: true,
}))
vi.mock("@/lib/store/useOpsStore", () => ({
  useOpsStore: (selector: (state: typeof fixture) => unknown) => selector(fixture),
  useSiteScopedEquipment: () => fixture.equipment,
}))
vi.mock("@/components/shared/PeriodFilters", () => ({ PeriodFilters: () => null }))

beforeEach(() => {
  fixture.equipment = [{ ...unknownEquipment, id: "TRK-010", code: "TRK-010", type: "haul_truck" }]
  fixture.shifts = [{ id: "shift-test", name: "Matin", startHour: 6, endHour: 14,
    windowStart: "2026-01-29T06:00:00Z", windowEnd: "2026-01-29T14:00:00Z" }]
  fixture.simNowIso = "2026-01-29T08:00:00Z"
  fixture.timelineSegments = [{ id: "seg-test", equipmentId: "TRK-010", state: "attente_charge",
    start: Date.parse("2026-01-29T07:00:00Z"), end: Date.parse("2026-01-29T07:30:00Z"), zoneName: null }]
  fixture.analysisTimelineSegments = fixture.timelineSegments
})

it("main Film renders the same persisted segment used by the mini-film", () => {
  const html = renderToStaticMarkup(createElement(Film))
  expect(html).toContain("TRK-010")
  expect(html).toContain("Film · focus poste")
  expect(html).toContain("left:240px") // 1h into the 2h operational window
  const mini = renderToStaticMarkup(createElement(MiniTimelineStrip, {
    segments: fixture.timelineSegments, rangeStart: Date.parse(fixture.shifts[0].windowStart!),
    rangeEnd: Date.parse(fixture.simNowIso!),
  }))
  expect(mini).toContain("left:50%")
  expect(mini).toContain("width:25%")
})

it("an unstarted reset window is unavailable, never replaced with demo history", () => {
  fixture.simNowIso = fixture.shifts[0].windowStart!
  fixture.timelineSegments = []
  fixture.analysisTimelineSegments = []
  const html = renderToStaticMarkup(createElement(Film))
  expect(html).toContain("Fenêtre opérationnelle indisponible ou poste non commencé")
  expect(html).not.toContain("seg-test")
})

it("historical Film excludes segments after the selected shift", () => {
  fixture.simNowIso = "2026-01-30T08:00:00Z"
  fixture.timelineSegments = [{ ...fixture.timelineSegments[0],
    start: Date.parse("2026-01-29T15:00:00Z"), end: Date.parse("2026-01-29T16:00:00Z") }]
  fixture.analysisTimelineSegments = fixture.timelineSegments
  const html = renderToStaticMarkup(createElement(Film))
  expect(html).not.toContain('title="Attente ·')
  expect(html).toContain("TRK-010")
})

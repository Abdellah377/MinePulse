import { createElement } from "react"
import { readFileSync } from "node:fs"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"
import type { Equipment, Shift, TimelineSegment } from "@/lib/mock/types"
import { unknownEquipment } from "@/test/aiFixtures"
import { formatElapsedHms, formatTimeHms } from "@/lib/format"
import Film, { FilmDetailPanel } from "./Film"
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

it("event detail shows factual fields only, without Cause or IA tabs", () => {
  const segment = fixture.timelineSegments[0]
  const html = renderToStaticMarkup(createElement(FilmDetailPanel, {
    selection: { type: "segment", equipmentId: "TRK-010", segment },
    equipment: fixture.equipment,
    allSegmentsByEquipment: new Map([["TRK-010", [segment]]]),
    rangeStart: Date.parse(fixture.shifts[0].windowStart!),
    rangeEnd: Date.parse(fixture.simNowIso!),
    onOpenEquipment: vi.fn(),
  }))
  expect(html).toContain("Attente de chargement")
  expect(html).toContain("TRK-010")
  expect(html).toContain(formatTimeHms(segment.start))
  expect(html).toContain(formatTimeHms(segment.end))
  expect(html).toContain(formatElapsedHms(segment.end - segment.start))
  expect(html).toContain("Ouvrir l’équipement")
  expect(html).toContain("Zone")
  expect(html).not.toContain("Faits")
  expect(html).not.toContain("Cause")
  expect(html).not.toMatch(/>IA</)
  expect(html).not.toContain("Analyse IA")
  expect(html).not.toContain("Confiance")
  expect(html).not.toContain("TabsTrigger")
})

it("switching segments updates state, times, and zone", () => {
  const first = fixture.timelineSegments[0]
  const second: TimelineSegment = {
    ...first,
    id: "seg-charge",
    state: "chargement",
    start: Date.parse("2026-01-29T07:30:00Z"),
    end: Date.parse("2026-01-29T07:42:00Z"),
    zoneName: "Banc B",
  }
  const props = {
    equipment: fixture.equipment,
    allSegmentsByEquipment: new Map([["TRK-010", [first, second]]]),
    rangeStart: Date.parse(fixture.shifts[0].windowStart!),
    rangeEnd: Date.parse(fixture.simNowIso!),
    onOpenEquipment: vi.fn(),
  }
  const firstHtml = renderToStaticMarkup(createElement(FilmDetailPanel, {
    ...props,
    selection: { type: "segment", equipmentId: "TRK-010", segment: first },
  }))
  const secondHtml = renderToStaticMarkup(createElement(FilmDetailPanel, {
    ...props,
    selection: { type: "segment", equipmentId: "TRK-010", segment: second },
  }))
  expect(firstHtml).toContain("Attente de chargement")
  expect(firstHtml).not.toContain("Banc B")
  expect(secondHtml).toContain("Chargement")
  expect(secondHtml).toContain("Banc B")
  expect(secondHtml).toContain(formatTimeHms(second.start))
  expect(secondHtml).not.toContain(formatTimeHms(first.start))
})

it("Film does not start investigations or load AI placeholders when an event is selected", () => {
  const source = readFileSync("src/pages/supervision/Film.tsx", "utf8")
  expect(source).not.toContain("filmSegmentInsight")
  expect(source).not.toContain("AiSlot")
  expect(source).not.toContain("useInvestigationStore")
  expect(source).not.toContain("aiApi")
  expect(source).not.toContain("TabsTrigger")
  expect(source).not.toContain('value="cause"')
  expect(source).not.toContain('value="ia"')
  expect(readFileSync("src/lib/ai/placeholders.ts", "utf8")).not.toContain("filmSegmentInsight")
})

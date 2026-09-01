import { expect, it } from "vitest"

import type { Shift, TimelineSegment } from "@/lib/mock/types"

import {
  analysisWindowMs,
  equipmentIdsMatching,
  segmentsIntersectingWindow,
  shiftsOverlappingPeriod,
} from "./analysisWindow"
import { POSTE_SELECTOR_OPTIONS } from "./shiftLabel"

const shift = (partial: Partial<Shift> & Pick<Shift, "id" | "name">): Shift => ({
  startHour: 6,
  endHour: 14,
  ...partial,
})

const roster: Shift[] = [
  shift({
    id: "nuit-27",
    name: "Poste nuit",
    startHour: 22,
    endHour: 6,
    windowStart: "2026-01-27T22:00:00.000Z",
    windowEnd: "2026-01-28T06:00:00.000Z",
  }),
  shift({
    id: "matin-28",
    name: "Poste matin",
    windowStart: "2026-01-28T06:00:00.000Z",
    windowEnd: "2026-01-28T14:00:00.000Z",
  }),
  shift({
    id: "apm-28",
    name: "Poste après-midi",
    startHour: 14,
    endHour: 22,
    windowStart: "2026-01-28T14:00:00.000Z",
    windowEnd: "2026-01-28T22:00:00.000Z",
  }),
  shift({
    id: "nuit-28",
    name: "Poste nuit",
    startHour: 22,
    endHour: 6,
    windowStart: "2026-01-28T22:00:00.000Z",
    windowEnd: "2026-01-29T06:00:00.000Z",
  }),
  shift({
    id: "matin-29",
    name: "Poste matin",
    windowStart: "2026-01-29T06:00:00.000Z",
    windowEnd: "2026-01-29T14:00:00.000Z",
  }),
  shift({
    id: "nuit-29",
    name: "Poste nuit",
    startHour: 22,
    endHour: 6,
    windowStart: "2026-01-29T22:00:00.000Z",
    windowEnd: "2026-01-30T06:00:00.000Z",
  }),
  shift({
    id: "matin-30",
    name: "Poste matin",
    windowStart: "2026-01-30T06:00:00.000Z",
    windowEnd: "2026-01-30T14:00:00.000Z",
  }),
  shift({
    id: "apm-30",
    name: "Poste après-midi",
    startHour: 14,
    endHour: 22,
    windowStart: "2026-01-30T14:00:00.000Z",
    windowEnd: "2026-01-30T22:00:00.000Z",
  }),
  shift({
    id: "nuit-30",
    name: "Poste nuit",
    startHour: 22,
    endHour: 6,
    windowStart: "2026-01-30T22:00:00.000Z",
    windowEnd: "2026-01-31T06:00:00.000Z",
  }),
]

it("A: 30 Jan + matin → only that morning window", () => {
  const rows = shiftsOverlappingPeriod(roster, "2026-01-30", "2026-01-30", "matin")
  expect(rows.map((row) => row.id)).toEqual(["matin-30"])
  const window = analysisWindowMs(roster, "2026-01-30", "2026-01-30", "matin", "2026-01-30T18:00:00.000Z")
  expect(window?.startMs).toBe(Date.parse("2026-01-30T06:00:00.000Z"))
  expect(window?.endMs).toBe(Date.parse("2026-01-30T14:00:00.000Z"))
})

it("B: 28–30 Jan + nuit → overlapping night shifts only, including overnight into the 28th", () => {
  const rows = shiftsOverlappingPeriod(roster, "2026-01-28", "2026-01-30", "nuit")
  expect(rows.map((row) => row.id)).toEqual(["nuit-27", "nuit-28", "nuit-29", "nuit-30"])
})

it("C: period window ∩ equipment keeps only matching segments", () => {
  const window = analysisWindowMs(roster, "2026-01-30", "2026-01-30", "matin", "2026-01-30T18:00:00.000Z")
  expect(window).toBeTruthy()
  const segments: TimelineSegment[] = [
    {
      id: "trk",
      equipmentId: "TRK-010",
      state: "attente_charge",
      start: Date.parse("2026-01-30T07:00:00.000Z"),
      end: Date.parse("2026-01-30T07:30:00.000Z"),
      zoneName: null,
    },
    {
      id: "exc-out",
      equipmentId: "EXC-001",
      state: "chargement",
      start: Date.parse("2026-01-30T15:00:00.000Z"),
      end: Date.parse("2026-01-30T15:20:00.000Z"),
      zoneName: null,
    },
    {
      id: "exc-in",
      equipmentId: "EXC-001",
      state: "chargement",
      start: Date.parse("2026-01-30T08:00:00.000Z"),
      end: Date.parse("2026-01-30T08:10:00.000Z"),
      zoneName: null,
    },
  ]
  const ids = equipmentIdsMatching(
    [
      { id: "TRK-010", type: "haul_truck", code: "TRK-010" },
      { id: "EXC-001", type: "excavator", code: "EXC-001" },
    ],
    "haul_truck",
    ""
  )
  const visible = segmentsIntersectingWindow(segments, window!.startMs, window!.endMs, ids)
  expect(visible.map((row) => row.id)).toEqual(["trk"])
})

it("D: Tous les postes keeps all three names in range and does not add selector options", () => {
  const rows = shiftsOverlappingPeriod(roster, "2026-01-30", "2026-01-30", "all")
  expect(new Set(rows.map((row) => row.name))).toEqual(
    new Set(["Poste matin", "Poste après-midi", "Poste nuit"])
  )
  expect(POSTE_SELECTOR_OPTIONS).toHaveLength(4)
  const later = shiftsOverlappingPeriod(roster, "2026-01-28", "2026-01-30", "all")
  expect(later.length).toBeGreaterThan(rows.length)
  expect(POSTE_SELECTOR_OPTIONS).toHaveLength(4)
})

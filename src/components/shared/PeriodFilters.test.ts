import { readFileSync } from "node:fs"
import { expect, it } from "vitest"

import { POSTE_SELECTOR_OPTIONS } from "@/lib/ops/shiftLabel"

it("Poste selector is built from the canonical constant, not dated shift rows", () => {
  const source = readFileSync("src/components/shared/PeriodFilters.tsx", "utf8")
  expect(source).toContain("POSTE_SELECTOR_OPTIONS")
  expect(source).not.toContain("uniqueShifts")
  expect(source).not.toContain("formatShiftLabel")
  expect(source).not.toContain("setSelectedShift")
  expect(POSTE_SELECTOR_OPTIONS.map((row) => row.name)).toEqual([
    "Tous les postes",
    "Poste matin",
    "Poste après-midi",
    "Poste nuit",
  ])
})

it("uses native date inputs, Période/Poste labels, and a reset control", () => {
  const source = readFileSync("src/components/shared/PeriodFilters.tsx", "utf8")
  expect(source).toMatch(/Période[\s\S]*Poste/)
  expect(source).toContain('type="date"')
  expect(source).toContain("Réinitialiser les filtres")
  expect(source).toContain("Du")
  expect(source).toContain("Au")
})

import { expect, it } from "vitest"

import { CANONICAL_POSTES, POSTE_SELECTOR_OPTIONS, canonicalShiftName, posteFromShiftName } from "./shiftLabel"

it("maps French and English aliases to one canonical poste id", () => {
  expect(posteFromShiftName("Poste matin")).toBe("matin")
  expect(posteFromShiftName("morning")).toBe("matin")
  expect(posteFromShiftName("Poste après-midi")).toBe("apres-midi")
  expect(posteFromShiftName("afternoon")).toBe("apres-midi")
  expect(posteFromShiftName("Poste nuit")).toBe("nuit")
  expect(posteFromShiftName("night")).toBe("nuit")
})

it("keeps short display names for French and English aliases", () => {
  expect(canonicalShiftName("Poste matin")).toBe("Matin")
  expect(canonicalShiftName("morning")).toBe("Matin")
  expect(canonicalShiftName("Poste après-midi")).toBe("Après-midi")
  expect(canonicalShiftName("afternoon")).toBe("Après-midi")
  expect(canonicalShiftName("Poste nuit")).toBe("Nuit")
  expect(canonicalShiftName("night")).toBe("Nuit")
})

it("selector is always Tous plus the three canonical posts", () => {
  expect(CANONICAL_POSTES.map((row) => row.name)).toEqual([
    "Poste matin",
    "Poste après-midi",
    "Poste nuit",
  ])
  expect(POSTE_SELECTOR_OPTIONS.map((row) => row.name)).toEqual([
    "Tous les postes",
    "Poste matin",
    "Poste après-midi",
    "Poste nuit",
  ])
  expect(POSTE_SELECTOR_OPTIONS).toHaveLength(4)
})

import { expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { ROAD_CLASS_PAINT, ROAD_STATUS_PAINT } from "./roadStyle"

it("keeps OPEN, RESTRICTED, CLOSED, and UNKNOWN visually distinct", () => {
  const colors = [
    ROAD_STATUS_PAINT.OPEN.color,
    ROAD_STATUS_PAINT.RESTRICTED.color,
    ROAD_STATUS_PAINT.CLOSED.color,
    ROAD_STATUS_PAINT.UNKNOWN.color,
  ]
  expect(new Set(colors).size).toBe(4)
  expect(ROAD_STATUS_PAINT.OPEN.dash).toBeNull()
  expect(ROAD_STATUS_PAINT.RESTRICTED.dash).not.toBeNull()
  expect(ROAD_STATUS_PAINT.CLOSED.dash).not.toBeNull()
  expect(ROAD_CLASS_PAINT.main.color).toBe(ROAD_STATUS_PAINT.OPEN.color)
  expect(ROAD_CLASS_PAINT.unknown.color).toBe(ROAD_STATUS_PAINT.UNKNOWN.color)
})

it("legend and map layer use the same status colors", () => {
  const legend = readFileSync("src/components/map/MapLegend.tsx", "utf8")
  const layer = readFileSync("src/components/map/HaulRoadsLayer.tsx", "utf8")
  expect(legend).toContain("ROAD_STATUS_PAINT.OPEN.color")
  expect(legend).toContain("ROAD_STATUS_PAINT.RESTRICTED.color")
  expect(legend).toContain("ROAD_STATUS_PAINT.CLOSED.color")
  expect(legend).toContain("Ouverte")
  expect(legend).toContain("Restreinte")
  expect(legend).toContain("Fermée")
  expect(layer).toContain("ROAD_CLASS_PAINT")
  expect(layer).toContain("roadsCasing")
  expect(layer).toContain("selected")
  expect(ROAD_STATUS_PAINT.OPEN.color).toBe("#7CFFF0")
})

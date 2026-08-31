import { expect, it } from "vitest"
import {
  canSaveRoadTrace,
  geometryToPersist,
  insertMidpointOnLongestSegment,
  insertVertexOnPolyline,
  polylineDistanceKm,
  removeLastVertex,
} from "./roadGeometry"

const p = (x: number, y: number) => ({ x, y })

it("keeps every clicked vertex when persisting a new road", () => {
  const draftPoints = [p(0, 0), p(10, 4), p(18, 12), p(30, 8)]
  const persisted = geometryToPersist({ isCreating: true, draftPoints, roadEditingVertices: null })
  expect(persisted).toEqual(draftPoints)
  expect(persisted).toHaveLength(4)
})

it("does not rewrite geometry when only fromZone/toZone would change", () => {
  expect(
    geometryToPersist({
      isCreating: false,
      draftPoints: [],
      roadEditingVertices: null,
    })
  ).toBeUndefined()
})

it("enforces a 2-point minimum and does not auto-complete at two points", () => {
  expect(canSaveRoadTrace({ isCreating: true, draftPoints: [p(0, 0)], roadEditingVertices: null })).toBe(false)
  expect(canSaveRoadTrace({ isCreating: true, draftPoints: [p(0, 0), p(1, 1)], roadEditingVertices: null })).toBe(true)
  expect(
    canSaveRoadTrace({
      isCreating: true,
      draftPoints: [p(0, 0), p(1, 1), p(2, 2), p(3, 3)],
      roadEditingVertices: null,
    })
  ).toBe(true)
  expect(geometryToPersist({ isCreating: true, draftPoints: [p(0, 0)], roadEditingVertices: null })).toBeUndefined()
})

it("loads and persists moved vertices without collapsing to endpoints", () => {
  const edited = [p(1, 1), p(5, 8), p(12, 3), p(20, 4)]
  expect(
    geometryToPersist({ isCreating: false, draftPoints: [], roadEditingVertices: edited })
  ).toEqual(edited)
  expect(canSaveRoadTrace({ isCreating: false, draftPoints: [], roadEditingVertices: [p(0, 0)] })).toBe(false)
})

it("inserts an intermediate vertex and refuses to drop below two points", () => {
  const inserted = insertVertexOnPolyline([p(0, 0), p(10, 0)], p(5, 1))
  expect(inserted).toHaveLength(3)
  expect(inserted[1].x).toBe(5)
  expect(removeLastVertex(inserted)).toHaveLength(2)
  expect(removeLastVertex([p(0, 0), p(1, 1)])).toHaveLength(2)
  expect(insertMidpointOnLongestSegment([p(0, 0), p(10, 0), p(12, 0)])).toHaveLength(4)
})

it("computes full polyline distance longer than the origin-destination shortcut", () => {
  const direct = [p(0, 0), p(400, 0)]
  const bent = [p(0, 0), p(120, 180), p(260, -40), p(400, 0)]
  const bentKm = polylineDistanceKm(bent)
  const directKm = polylineDistanceKm(direct)
  expect(bentKm).not.toBeNull()
  expect(directKm).not.toBeNull()
  expect(bentKm as number).toBeGreaterThan(directKm as number)
})

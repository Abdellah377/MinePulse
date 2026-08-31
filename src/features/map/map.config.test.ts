import { readFileSync } from "node:fs"
import { expect, it } from "vitest"
import { routesToGeoJSON } from "./map.utils"
import type { RoutePath } from "@/lib/mock/types"

it("normal Carte is read-only until Configurer la carte", () => {
  const carte = readFileSync("src/pages/supervision/Carte.tsx", "utf8")
  const controls = readFileSync("src/components/map/MapControls.tsx", "utf8")
  expect(controls).toContain("Configurer la carte")
  expect(controls).toContain("Quitter la configuration")
  expect(controls).not.toContain("Nouvelle zone")
  expect(controls).not.toContain("Modifier les zones")
  expect(carte).toContain("configMode")
  expect(carte).toContain("window.confirm")
  expect(carte).not.toContain("onAddZone")
  expect(carte).toContain('useState(false)')
  expect(carte).toMatch(/const \[showRoadsLayer, setShowRoadsLayer\] = useState\(false\)/)
  expect(carte).toContain("roadsVisible")
  expect(carte).not.toContain("routableEdges")
  expect(carte).not.toContain("canReach")
  expect(carte).toContain("roadEditingVertices")
  expect(carte).toContain("geometryToPersist")
  expect(carte).toContain("startRoadTraceEdit")
  expect(carte).toContain("configMode && (isEditingVertices || isEditingRoadVertices)")
  expect(controls).toContain("Configurer la carte")
})

it("road GeoJSON paints persisted status, not zone-type inference", () => {
  const utils = readFileSync("src/features/map/map.utils.ts", "utf8")
  expect(utils).not.toMatch(/restreinte.*restricted/)
  const closed: RoutePath = {
    id: "R-03",
    fromZoneId: "A",
    toZoneId: "B",
    points: [
      { x: 0, y: 0 },
      { x: 10, y: 10 },
    ],
    distanceKm: 2,
    siteId: "s",
    status: "CLOSED",
    speedLimitKmh: null,
    description: null,
    statusReason: "BLASTING",
    statusNote: null,
  }
  const geo = routesToGeoJSON([closed])
  expect(geo.features[0].properties.roadClass).toBe("closed")
  expect(geo.features[0].properties.status).toBe("CLOSED")
  const unknown = routesToGeoJSON([{ ...closed, status: undefined }])
  expect(unknown.features[0].properties.roadClass).toBe("unknown")
  expect(unknown.features[0].properties.status).toBe("UNKNOWN")
})

it("HaulRoadsLayer click inspects without posting", () => {
  const layer = readFileSync("src/components/map/HaulRoadsLayer.tsx", "utf8")
  expect(layer).toContain("onRoadClick")
  expect(layer).not.toContain("createRoad")
  expect(layer).not.toContain("patchRoad")
})

it("road drawing keeps every click until save, and zone vertex editing stays intact", () => {
  const carte = readFileSync("src/pages/supervision/Carte.tsx", "utf8")
  const roadsPanel = readFileSync("src/components/map/RoadEditorPanel.tsx", "utf8")
  const zonesPanel = readFileSync("src/components/map/ZoneEditorPanel.tsx", "utf8")
  expect(roadsPanel).toContain("Modifier le tracé")
  expect(roadsPanel).toContain("Cliquez sur la carte pour ajouter les sommets de la route.")
  expect(roadsPanel).toContain("pointLabel")
  expect(roadsPanel).toContain("défini")
  expect(zonesPanel).toContain("Éditer sommets")
  expect(zonesPanel).toContain("Nouvelle zone")
  expect(carte).toContain("editingVertices")
  expect(carte).toContain("roadEditingVertices")
  expect(carte).not.toContain("buildDemoRoutes")
  const canvasStart = carte.indexOf("const handleCanvasClick")
  const canvasEnd = carte.indexOf("function undoLastPoint")
  const canvas = carte.slice(canvasStart, canvasEnd)
  expect(canvas).toContain("setDraftPoints((pts) => [...pts, lngLatToWorkspace(lngLat)])")
  expect(canvas).not.toContain("handleSaveRoad")
  const cancel = carte.slice(carte.indexOf("function handleCancelDraft"), carte.indexOf("function startRoadTraceEdit"))
  expect(cancel).toContain("setRoadEditingVertices(null)")
  expect(cancel).not.toContain("persistRoutes")
  expect(cancel).not.toContain("patchRoad")
  expect(carte).toContain("enabled={configMode && (isEditingVertices || isEditingRoadVertices)}")
})

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"
import { result } from "@/test/aiFixtures"
import type { Alert } from "@/lib/mock/types"
import type { InvestigationEntry } from "@/lib/store/useInvestigationStore"
import type { WorkspaceTab } from "@/lib/workspace/types"
import AlertesIA from "@/pages/AlertesIA"

const fixtures = vi.hoisted(() => {
  const currentA: Alert = {
    id: "alert-current-a",
    severity: "warning",
    status: "new",
    title: "Arrêt inattendu TRK-001",
    description: "Camion arrêté hors cycle prévu.",
    equipmentId: "TRK-001",
    zoneId: "Z-1",
    location: "Banc A",
    category: "EQUIPMENT_ANOMALY",
    source: "RULE",
    createdAt: 3,
    updatedAt: 3,
    assignedTo: null,
    resolution: null,
  }
  const currentB: Alert = {
    id: "alert-current-b",
    severity: "critical",
    status: "new",
    title: "Perte de communication TRK-004",
    description: "Télémetrie absente depuis plusieurs minutes.",
    equipmentId: "TRK-004",
    zoneId: "Z-2",
    location: "Banc B",
    category: "CONNECTIVITY_ISSUE",
    source: "FMS",
    createdAt: 2,
    updatedAt: 2,
    assignedTo: null,
    resolution: null,
  }
  const prediction: Alert = {
    id: "alert-pred-1",
    severity: "warning",
    status: "new",
    title: "Risque mécanique prédit — TRK-010",
    description: "Risque mécanique prédit élevé dans les 60 prochaines minutes.",
    equipmentId: "TRK-010",
    zoneId: "Z-1",
    location: "Banc A",
    category: "PREDICTED_MECHANICAL_FAILURE_RISK",
    source: "PREDICTION",
    createdAt: 1,
    updatedAt: 1,
    assignedTo: null,
    resolution: null,
    prediction: {
      probability: 0.74,
      threshold: 0.41,
      horizonMinutes: 60,
      dataClass: "synthetic_prototype",
      modelVersion: "failure_risk_v1",
    },
  }
  return {
    currentA,
    currentB,
    prediction,
    alerts: [currentA, currentB, prediction] as Alert[],
    entry: undefined as InvestigationEntry | undefined,
    lookup: vi.fn(),
    start: vi.fn(),
    demo: vi.fn(() => { throw new Error("Mock intelligence leaked") }),
  }
})

vi.mock("@/lib/api/client", () => ({ useApiMode: true }))
vi.mock("@/lib/ai/alertIntelligence", () => ({
  buildCurrentIntelligence: fixtures.demo,
  buildPredictionIntelligence: fixtures.demo,
  getIntelligenceItem: fixtures.demo,
  actionsContextFromItem: fixtures.demo,
}))
vi.mock("@/lib/store/useOpsStore", () => {
  const ops = {
    get alerts() { return fixtures.alerts },
    sites: [{ id: "SITE-17", databaseId: 17, name: "Site opérationnel" }],
    shifts: [{ id: "shift-29", databaseId: 29 }],
    selectedSiteId: "SITE-17",
    selectedShiftId: "shift-29",
    equipment: [],
    zones: [{ id: "Z-1", name: "Banc A" }, { id: "Z-2", name: "Banc B" }],
    timelineSegments: [],
    apiPollError: null,
    apiBootstrapped: true,
  }
  return {
    useOpsStore: (selector?: (s: typeof ops) => unknown) => selector ? selector(ops) : ops,
    useSiteScopedEquipment: () => [],
    useSiteScopedZones: () => ops.zones,
  }
})
vi.mock("@/lib/store/useWorkspaceStore", () => ({
  useWorkspaceStore: (selector: (s: unknown) => unknown) => selector({
    openWorkspace: vi.fn(),
    patchTabContext: vi.fn(),
    tabState: {},
    setTabState: vi.fn(),
  }),
}))
vi.mock("@/lib/store/useInvestigationStore", () => {
  const state = () => ({
    entries: {
      "17:29:alert-current-a": fixtures.entry,
      "17:29:alert-pred-1": fixtures.entry,
    },
    lookup: fixtures.lookup,
    start: fixtures.start,
    retrieve: vi.fn(),
  })
  return {
    investigationKey: (scope: { site_id: number; shift_id?: number | null; source_record_id: string }) =>
      `${scope.site_id}:${scope.shift_id ?? "any"}:${scope.source_record_id}`,
    useInvestigationStore: Object.assign(
      (selector: (s: ReturnType<typeof state>) => unknown) => selector(state()),
      { getState: state },
    ),
  }
})

function alertsTab(context: WorkspaceTab["context"]): WorkspaceTab {
  return {
    id: "tab-alerts",
    type: "alerts",
    title: "Alertes IA",
    module: "alertes",
    context,
    isPinned: false,
    isDirty: false,
    createdAt: 1,
    lastActivatedAt: 1,
  }
}

function renderAlertes(tab?: WorkspaceTab) {
  return renderToStaticMarkup(createElement<Partial<{ tab: WorkspaceTab }>>(AlertesIA, tab ? { tab } : {}))
}

beforeEach(() => {
  vi.clearAllMocks()
  fixtures.entry = undefined
  fixtures.alerts = [fixtures.currentA, fixtures.currentB, fixtures.prediction]
})

it("En cours is the default tab and both tabs are enabled with unfiltered counts", () => {
  const html = renderAlertes()
  expect(html).toMatch(/shadow-sm[^>]*>En cours/)
  expect(html).not.toMatch(/shadow-sm[^>]*>Prédictions/)
  expect(html).not.toMatch(/<button[^>]*disabled[^>]*>[\s\S]{0,120}Prédictions/)
  expect(html).not.toContain("Prédictions non disponibles")
  expect(html).toMatch(/En cours<span[^>]*>2<\/span>/)
  expect(html).toMatch(/Prédictions<span[^>]*>1<\/span>/)
  expect(html).toContain(fixtures.currentA.title)
  expect(html).toContain(fixtures.currentB.title)
  expect(html).not.toContain(fixtures.prediction.title)
  expect(fixtures.demo).not.toHaveBeenCalled()
})

it("Prédictions tab shows only prediction-source alerts and labels them as Prédiction", () => {
  const html = renderAlertes(alertsTab({ predictionId: fixtures.prediction.id }))
  expect(html).toMatch(/shadow-sm[^>]*>Prédictions/)
  expect(html).not.toMatch(/shadow-sm[^>]*>En cours/)
  expect(html).toContain(fixtures.prediction.title)
  expect(html).toContain("Prédiction")
  expect(html).toContain("Modèle prédictif")
  expect(html).toContain("74 %")
  expect(html).toContain("60 min")
  expect(html).toContain("Prédiction prototype")
  expect(html).not.toContain(fixtures.currentA.title)
  expect(html).not.toContain(fixtures.currentB.title)
  expect(html).not.toContain("Le camion va tomber en panne")
  expect(html).toContain("Pourquoi ?")
  expect(fixtures.demo).not.toHaveBeenCalled()
  expect(fixtures.start).not.toHaveBeenCalled()
})

it("opening a prediction via alertId does not leave En cours detail visible", () => {
  const html = renderAlertes(alertsTab({ alertId: fixtures.prediction.id }))
  expect(html).toContain(fixtures.prediction.title)
  expect(html).not.toContain(fixtures.currentA.title)
  expect(html).toMatch(/shadow-sm[^>]*>Prédictions/)
})

it("renders the empty prediction state without falling back to demo cards", () => {
  fixtures.alerts = [fixtures.currentA, fixtures.currentB]
  const html = renderAlertes(alertsTab({ predictionId: "alert-missing" }))
  expect(html).toContain("Aucune prédiction active.")
  expect(html).not.toContain(fixtures.currentA.title)
  expect(html).not.toContain(fixtures.prediction.title)
  expect(html).toMatch(/Prédictions<span[^>]*>0<\/span>/)
  expect(fixtures.demo).not.toHaveBeenCalled()
})

it("shows an existing automatic investigation for a prediction without posting again", () => {
  fixtures.entry = {
    phase: "ready",
    result: {
      ...result,
      trigger: {
        ...result.trigger,
        trigger_type: "PREDICTED_MECHANICAL_FAILURE_RISK",
        trigger_source: "AUTOMATIC_MONITORING",
        source_record_id: fixtures.prediction.id,
      },
    },
  }
  const html = renderAlertes(alertsTab({ predictionId: fixtures.prediction.id }))
  expect(html).toContain("Détecté automatiquement")
  expect(html).toContain(result.conclusion!.summary)
  expect(fixtures.start).not.toHaveBeenCalled()
  expect(fixtures.demo).not.toHaveBeenCalled()
})

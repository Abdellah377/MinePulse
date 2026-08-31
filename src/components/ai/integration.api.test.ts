import { createElement } from "react"
import { readFileSync } from "node:fs"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"
import { result, alert } from "@/test/aiFixtures"
import type { InvestigationEntry } from "@/lib/store/useInvestigationStore"
import type { WorkspaceTab } from "@/lib/workspace/types"
import AlertesIA from "@/pages/AlertesIA"
import ActionsIA from "@/pages/ActionsIA"
import { InvestigationResultView } from "./InvestigationResultView"
import { investigationStatus } from "@/lib/ai/investigationPresentation"

const mocks = vi.hoisted(() => ({ entry: undefined as InvestigationEntry | undefined, lookup: vi.fn(), start: vi.fn(), retrieve: vi.fn(), demo: vi.fn(() => { throw new Error("Mock intelligence leaked") }) }))
vi.mock("@/lib/api/client", () => ({ useApiMode: true }))
vi.mock("@/lib/ai/alertIntelligence", () => ({ buildCurrentIntelligence: mocks.demo, buildPredictionIntelligence: mocks.demo, getIntelligenceItem: mocks.demo, actionsContextFromItem: mocks.demo }))
vi.mock("@/lib/ai/dispatch", () => ({ dispatchOptimizationBundle: mocks.demo, projectSnapshot: mocks.demo, DISPATCH_KIND_LABEL: {} }))
vi.mock("@/lib/store/useOpsStore", async () => {
  const { alert } = await import("@/test/aiFixtures")
  const ops = { alerts: [alert], sites: [{ id: "SITE-17", databaseId: 17, name: "Site opérationnel" }], shifts: [{ id: "shift-29", databaseId: 29 }], selectedSiteId: "SITE-17", selectedShiftId: "shift-29", equipment: [], zones: [], apiPollError: null, apiBootstrapped: true }
  return { useOpsStore: (selector?: (s: typeof ops) => unknown) => selector ? selector(ops) : ops, useSiteScopedEquipment: () => [], useSiteScopedZones: () => [] }
})
vi.mock("@/lib/store/useWorkspaceStore", () => ({ useWorkspaceStore: (selector: (s: unknown) => unknown) => selector({ openWorkspace: vi.fn(), patchTabContext: vi.fn(), tabState: {}, setTabState: vi.fn() }) }))
vi.mock("@/lib/store/useInvestigationStore", () => {
  const state = () => ({ entries: { "17:29:alert-42": mocks.entry, "3fc18d28-06de-4a75-9044-adad97ddcc80": mocks.entry }, lookup: mocks.lookup, start: mocks.start, retrieve: mocks.retrieve })
  return { investigationKey: () => "17:29:alert-42", useInvestigationStore: Object.assign((selector: (s: ReturnType<typeof state>) => unknown) => selector(state()), { getState: state }) }
})
beforeEach(() => { vi.clearAllMocks(); mocks.entry = undefined })

it("API Alertes IA renders backend LangGraph output and qualitative confidence", () => {
  mocks.entry = { phase: "ready", result }
  const html = renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain(result.conclusion!.summary)
  expect(html).toContain(result.recommendation!.description)
  expect(html).toContain("Faible")
  expect(html).toContain("Impact non quantifié")
  expect(html).toContain(alert.title)
  expect(html).toContain("Investigation demandée")
  expect(html).toMatch(/shadow-sm[^>]*>En cours/)
  expect(html).toContain("Prédictions")
  expect(html).not.toContain("Prédictions non disponibles")
  expect(html).not.toMatch(/disabled[^>]*>[\s\S]{0,80}Prédictions/)
  expect(html).not.toContain("0%")
  expect(mocks.demo).not.toHaveBeenCalled()
  for (const section of ["Incident", "Pourquoi MinePulse pense cela", "Ce qui semble s’être passé", "Action recommandée", "Impact", "Liens utiles", "Panel IA", "Cause non déterminée", "Confiance causale", "Ouvrir l’équipement"]) expect(html).toContain(section)
  expect(html).toContain("max-w-[360px]")
  expect(html).toContain("max-w-[340px]")
  const panel = html.split("data-testid=\"panel-ia\"")[1]?.split("</aside>")[0] ?? ""
  expect(panel).toContain("Cause non déterminée")
  expect(panel).toContain("Confiance causale")
  expect(panel).toContain("Ouvrir Actions IA")
  expect(panel).toContain("Actualiser le résultat")
  expect(panel).toContain("line-clamp-2")
  expect(panel).not.toContain("Impact non quantifié")
  expect(panel).not.toContain(result.investigation_id)
})
it("labels persisted automatic monitoring results without starting a frontend investigation", () => {
  mocks.entry = {
    phase: "ready",
    result: { ...result, trigger: { ...result.trigger, trigger_source: "AUTOMATIC_MONITORING" } },
  }
  const html = renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain("Détecté automatiquement")
  expect(html).toContain("Pourquoi ?")
  expect(html).toContain("ai-why-report")
  expect(mocks.start).not.toHaveBeenCalled()
  expect(mocks.demo).not.toHaveBeenCalled()
})
it("Pourquoi ? is available without an investigation and does not POST", () => {
  const html = renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain("Pourquoi ?")
  expect(html).toContain("Voir dans Actions IA")
  expect(html).toContain("Investiguer")
  expect(html).toContain("Analyse IA non lancée")
  expect(mocks.start).not.toHaveBeenCalled()
})
it("render and rerender cannot create investigations; pending is not confidence zero", () => {
  const html = renderToStaticMarkup(createElement(AlertesIA))
  renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain("Analyse IA non lancée")
  expect(html).not.toMatch(/Confiance.*0\s*%/)
  expect(mocks.start).not.toHaveBeenCalled()
})
it("API Actions IA uses only the persisted UUID result, without dispatch scenarios", () => {
  mocks.entry = { phase: "ready", result }
  const tab: WorkspaceTab = { id: "tab-actions", type: "actions", title: "Actions IA", module: "actions", context: { investigationId: result.investigation_id, alertId: alert.id }, isPinned: false, isDirty: false, createdAt: 1, lastActivatedAt: 1 }
  const html = renderToStaticMarkup(createElement<Partial<{ tab: WorkspaceTab }>>(ActionsIA, { tab }))
  expect(html).toContain(result.recommendation!.description)
  expect(html).toContain("lg:col-span-7")
  expect(html).toContain("lg:col-span-5")
  expect(html).toContain("Accepter")
  expect(html).toContain("Modifier")
  expect(html).toContain("Rejeter")
  expect(html).toContain("Discuter cette recommandation")
  expect(html).toContain("Pourquoi ?")
  expect(html).toContain("En attente de décision")
  expect(html).not.toContain("Préparer")
  expect(html).not.toContain(">Marquer<")
  expect(mocks.demo).not.toHaveBeenCalled()
})
it("API Actions IA decision and reject labels cover accept, modify, and reject", () => {
  const labels = readFileSync("src/lib/api/types/actionsIa.ts", "utf8")
  expect(labels).toContain("Recommandation acceptée")
  expect(labels).toContain("Action modifiée par l’opérateur")
  expect(labels).toContain("Recommandation rejetée")
  expect(labels).toContain("Suivi ouvert")
  expect(labels).toContain("Suivi clôturé")
  expect(labels).toContain("Impossible opérationnellement")
  expect(labels).toContain("Contrainte non connue par l’IA")
  expect(labels).toContain("Risque sécurité")
  expect(labels).toContain("Mauvaise priorité production")
  expect(labels).toContain("Information incorrecte")
  expect(labels).toContain("Meilleure alternative")
  expect(labels).toContain("Autre")
})

it("Actions IA Pourquoi and decisions do not start investigations; only discussion posts generate_reply", () => {
  const source = readFileSync("src/components/ai/InvestigationActions.tsx", "utf8")
  expect(source).toMatch(/AiWhyButton/)
  expect(source).toMatch(/putDecision/)
  expect(source).toMatch(/patchFollowUp/)
  expect(source).toMatch(/follow_up_status: "RESOLVED"/)
  expect(source).toMatch(/DECISION_STATUS_LABEL/)
  expect(source).toMatch(/FOLLOW_UP_STATUS_LABEL/)
  expect(source).toMatch(/generate_reply: true/)
  expect(source).toMatch(/Marquer comme traité/)
  expect(source).toMatch(/Optimiser/)
  expect(source).not.toMatch(/Ouvrir Alertes IA/)
  expect(source).not.toMatch(/saveDecision\("RESOLVED"\)/)
  expect(source).not.toMatch(/aiApi\.create\(/)
  expect(source).not.toMatch(/\.start\(/)
})

it("Pourquoi ? only scrolls to the existing report and never starts an investigation", () => {
  const source = readFileSync("src/components/ai/InvestigationAlerts.tsx", "utf8")
  expect(source).toMatch(/AiWhyButton[\s\S]{0,180}scrollIntoView/)
  expect(source).toMatch(/onClick=\{investigate\}/)
  expect(source).not.toMatch(/AiWhyButton[\s\S]{0,220}start\(/)
  expect(source).not.toMatch(/AiWhyButton[\s\S]{0,220}investigate\(/)
})
it("running state disables manual creation and persisted provider errors do not expose raw messages", () => {
  mocks.entry = { phase: "running" }
  let html = renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain("Analyse IA en cours")
  expect(html).toContain("Pourquoi ?")
  expect(html).not.toContain(result.recommendation!.description)
  mocks.entry = { phase: "ready", result: { ...result, status: "FAILED", conclusion: null, recommendation: null, error: { stage: "analyze", error_type: "ProviderTimeoutError", message: "secret SDK response" } } }
  html = renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain("Délai de l’analyse IA dépassé")
  expect(html).not.toContain("secret SDK response")
})
it("failure leaves the live panel unavailable, not populated with pseudo-AI", () => {
  mocks.entry = { phase: "error", error: "Fournisseur IA indisponible" }
  const html = renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain("Analyse indisponible")
  expect(html).not.toContain(result.conclusion!.summary)
  expect(mocks.demo).not.toHaveBeenCalled()
})
it("renders all lifecycle states distinctly and null evidence as unavailable", () => {
  expect(investigationStatus({ phase: "running" })).toBe("Analyse IA en cours")
  expect(investigationStatus({ phase: "ready", result })).toContain("non déterminée")
  expect(investigationStatus({ phase: "ready", result: { ...result, status: "FAILED" } })).toContain("Analyse indisponible")
  expect(investigationStatus({ phase: "ready", result: { ...result, status: "PENDING" } })).toContain("en attente")
  const html = renderToStaticMarkup(createElement(InvestigationResultView, { result }))
  expect(html).toContain("Indisponible (UNAVAILABLE)")
  expect(html).toContain("Cause non déterminée")
  expect(html).not.toMatch(/>0(?:&nbsp;|\s)*t</)
})

it("renders CONFIRMED, PROBABLE, and INCONCLUSIVE labels without false confidence", () => {
  const probable = {
    ...result,
    conclusion: {
      ...result.conclusion!,
      diagnosis_status: "PROBABLE" as const,
      root_cause: "Dégradation liée à la lubrification",
      reliable_root_cause: false,
      summary: "The available evidence supports lubrication-related degradation.",
      unresolved_uncertainties: ["The exact causal mechanism or failed component is not confirmed."],
    },
  }
  mocks.entry = { phase: "ready", result: probable }
  let html = renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain("Cause probable")
  expect(html).toContain("Dégradation liée à la lubrification")
  expect(html).toContain("n’est pas confirmé")
  expect(html).toContain("Confirmation incomplète")
  expect(html).not.toContain("Cause confirmée")
  expect(html).not.toContain("Conclusion non fiable")
  expect(html).not.toContain("Cause étayée")
  const probableView = renderToStaticMarkup(createElement(InvestigationResultView, { result: probable }))
  expect(probableView).toContain("Cause probable")
  expect(probableView).not.toContain("Cause confirmée")
  expect(probableView).not.toContain("Cause étayée")

  const confirmed = {
    ...result,
    status: "COMPLETED" as const,
    conclusion: {
      ...result.conclusion!,
      diagnosis_status: "CONFIRMED" as const,
      root_cause: "Panne mécanique confirmée par diagnostic",
      reliable_root_cause: true,
      summary: "Authoritative evidence supports a mechanical fault.",
      unresolved_uncertainties: [],
    },
  }
  mocks.entry = { phase: "ready", result: confirmed }
  html = renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain("Cause confirmée")
  expect(html).toContain("Panne mécanique confirmée par diagnostic")
  expect(html).not.toContain("Cause probable")

  mocks.entry = { phase: "ready", result }
  html = renderToStaticMarkup(createElement(AlertesIA))
  expect(html).toContain("Cause non déterminée")
  expect(html).toContain("preuve insuffisante")
})

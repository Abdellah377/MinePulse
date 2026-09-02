import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { CompactPlanImpact, OptimizationImpactCard } from "./OptimizationImpact"
import { classifyOptimizationImpact } from "@/lib/ai/optimizationDisplay"
import type { OptimizationCandidate } from "@/lib/api/types/optimization"

const plan = (overrides: Partial<OptimizationCandidate> = {}): OptimizationCandidate => ({
  candidateId: "opt",
  truckId: 1,
  truckCode: "TRK-1",
  loaderId: 10,
  loaderCode: "LD-1",
  destZoneCode: "D1",
  originZoneCode: "L1",
  roadIds: ["RD-1"],
  distanceKm: 4.8,
  travelMinutes: 9.1,
  waitMinutes: 5,
  score: 10.4,
  constraintNotes: [],
  rankReason: "score",
  ...overrides,
})

describe("OptimizationImpactCard", () => {
  it("renders feasible optimizer metrics with before/after", () => {
    const current = plan({ candidateId: "now", isCurrent: true, waitMinutes: 12, travelMinutes: 8.3, distanceKm: 5.2, score: 18 })
    const selected = plan({ candidateId: "opt", waitMinutes: 5, travelMinutes: 9.1, distanceKm: 4.8, score: 10.4 })
    const html = renderToStaticMarkup(createElement(OptimizationImpactCard, { view: classifyOptimizationImpact([current, selected], "opt") }))
    expect(html).toContain("Impact estimé")
    expect(html).toContain("12 min")
    expect(html).toContain("5 min")
    expect(html).toContain("8.3 min")
    expect(html).toContain("9.1 min")
    expect(html).toContain("4.8 km")
    expect(html).toContain("10.4")
    expect(html).toContain("amélioration")
    expect(html).toContain("dégradation")
    expect(html).toContain("min-w-0")
    expect(html).toContain("grid")
    expect(html).not.toContain("tonnage")
  })

  it("marks wait reduction as an improvement and travel increase as a trade-off", () => {
    const current = plan({ candidateId: "now", isCurrent: true, waitMinutes: 12, travelMinutes: 8, score: 20 })
    const selected = plan({ candidateId: "opt", waitMinutes: 5, travelMinutes: 9, score: 14 })
    const html = renderToStaticMarkup(createElement(OptimizationImpactCard, { view: classifyOptimizationImpact([current, selected], "opt") }))
    expect(html).toContain("text-accent")
    expect(html).toContain("text-warning")
    expect(html).toContain("amélioration")
    expect(html).toContain("dégradation")
  })

  it("does not show a null metric as zero", () => {
    const current = plan({ candidateId: "now", isCurrent: true, waitMinutes: 8, travelMinutes: 4, score: 12 })
    const selected = plan({ candidateId: "opt", waitMinutes: null, travelMinutes: 4, score: null })
    const html = renderToStaticMarkup(createElement(OptimizationImpactCard, { view: classifyOptimizationImpact([current, selected], "opt") }))
    expect(html).toContain("temps d’attente du chargeur indisponible")
    expect(html).not.toMatch(/>0 min</)
    expect(html.split("Non disponible").length).toBe(1)
  })

  it("shows a restrained current-plan state instead of zero-delta cards", () => {
    const current = plan({ candidateId: "now", isCurrent: true, waitMinutes: 10, travelMinutes: 3.9, score: 13.9 })
    const html = renderToStaticMarkup(createElement(OptimizationImpactCard, { view: classifyOptimizationImpact([current], "now") }))
    expect(html).toContain("Plan actuel sélectionné")
    expect(html).toContain("meilleur parmi les options évaluables")
    expect(html).not.toContain("→")
  })

  it("updates impact copy when selecting a better alternative without a zero-delta grid", () => {
    const current = plan({ candidateId: "now", isCurrent: true, waitMinutes: 10, travelMinutes: 4, score: 14 })
    const alt = plan({ candidateId: "alt", waitMinutes: 2, travelMinutes: 5, score: 7 })
    const currentHtml = renderToStaticMarkup(createElement(OptimizationImpactCard, { view: classifyOptimizationImpact([current, alt], "now") }))
    const altHtml = renderToStaticMarkup(createElement(OptimizationImpactCard, { view: classifyOptimizationImpact([current, alt], "alt") }))
    expect(currentHtml).toContain('data-testid="impact-estime"')
    expect(altHtml).toContain('data-testid="impact-estime"')
    expect(currentHtml).toContain("Plan actuel sélectionné")
    expect(currentHtml).not.toContain("→")
    expect(altHtml).toContain("10 min")
    expect(altHtml).toContain("2 min")
    expect(altHtml).toContain("→")
    expect(altHtml).toContain("plan actuel → plan sélectionné")
  })

  it("shows a restrained unavailable state when there is no impact data", () => {
    const html = renderToStaticMarkup(createElement(OptimizationImpactCard, { view: null }))
    expect(html).toContain("Non disponible")
    expect(html).toContain("Impact estimé")
    expect(html).not.toContain("bg-accent-soft/40")
  })
})

describe("CompactPlanImpact", () => {
  it("shows a compact preview for alternative candidates", () => {
    const html = renderToStaticMarkup(createElement(CompactPlanImpact, { plan: plan({ waitMinutes: 5, travelMinutes: 9, score: 14 }) }))
    expect(html).toContain("plan-impact-compact")
    expect(html).toContain("Attente")
    expect(html).toContain("5 min")
    expect(html).toContain("Trajet")
    expect(html).toContain("9 min")
    expect(html).toContain("Objectif")
    expect(html).toContain("14")
    expect(html).not.toContain("Impact estimé")
    expect(html).toContain("flex-wrap")
  })
})

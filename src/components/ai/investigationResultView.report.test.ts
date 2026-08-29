import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { InvestigationResultView } from "./InvestigationResultView"
import type { InvestigationResult } from "@/lib/api/types/ai"
import { result as baseResult } from "@/test/aiFixtures"

function mechanicalResult(status: "CONFIRMED" | "PROBABLE" | "INCONCLUSIVE" = "PROBABLE"): InvestigationResult {
  const conclusive = status !== "INCONCLUSIVE"
  return {
    ...baseResult,
    trigger: { ...baseResult.trigger, trigger_type: "EQUIPMENT_ANOMALY", subject: "EQUIPMENT", equipment_id: 16, payload: { title: "Arrêt mécanique" } },
    status: status === "CONFIRMED" ? "COMPLETED" : "COMPLETED_WITH_UNCERTAINTY",
    evidence: [
      {
        evidence_id: "ev-trends",
        kind: "DERIVED_METRIC",
        source_tool: "equipment_telemetry_trends",
        source_service: "app.oem.queries.get_equipment_signal_trends",
        metric: "equipment_telemetry_trends",
        value: {
          metrics: [
            { metric: "engine_temp_c", unit: "°C", sampleCount: 8, firstValue: 89.8, lastValue: 105.6, direction: "rising", lastObservedAt: "2026-08-26T07:29:00Z" },
            { metric: "coolant_temp_c", unit: "°C", sampleCount: 8, firstValue: 83.1, lastValue: 97.9, direction: "rising", lastObservedAt: "2026-08-26T07:29:00Z" },
            { metric: "oil_pressure_kpa", unit: "kPa", sampleCount: 8, firstValue: 426, lastValue: 329.8, direction: "falling", lastObservedAt: "2026-08-26T07:29:00Z" },
          ],
        },
        available: true,
        status: "AVAILABLE",
        unit: null,
        site_id: 17,
        shift_id: 29,
        equipment_id: 16,
        zone_id: null,
        observed_at: "2026-08-26T07:29:00Z",
        source_record_ids: ["equipment:16"],
        metadata: { preIncidentSampleCount: 8 },
        notes: null,
      },
      {
        evidence_id: "ev-oem",
        kind: "FACT",
        source_tool: "oem_errors",
        source_service: "app.oem.queries.error_codes",
        metric: "oem_errors",
        value: "Alerte température moteur élevée",
        available: true,
        status: "AVAILABLE",
        unit: null,
        site_id: 17,
        shift_id: 29,
        equipment_id: 16,
        zone_id: null,
        observed_at: "2026-08-26T07:24:00Z",
        source_record_ids: ["event:81"],
        metadata: {},
        notes: "Alerte OEM antérieure à l’arrêt.",
      },
    ],
    hypotheses: [{
      hypothesis_id: "hyp-thermal",
      statement: conclusive ? "Dégradation thermique du moteur" : "Surchauffe ou charge excessive",
      supporting_evidence_ids: conclusive ? ["ev-trends", "ev-oem"] : ["ev-trends"],
      contradictory_evidence_ids: conclusive ? [] : ["ev-oem"],
      confidence: conclusive ? "HIGH" : "LOW",
      causal_depth: conclusive ? 2 : 0,
      rationale: "Les tendances précèdent l’arrêt et évoluent de manière cohérente.",
    }],
    contradictions: conclusive ? [] : [{ description: "Le signal OEM ne permet pas d’identifier le composant exact.", evidence_ids: ["ev-oem"] }],
    requested_information: conclusive ? [] : [{ request_id: "req-1", request_type: "OEM_DIAGNOSTICS", equipment_id: 16, zone_id: null, start_time: null, end_time: null, parameters: [], reason: "Vérifier les codes de protection moteur." }],
    evidence_request_history: [{ signature: "oem:16", request: { request_id: "req-history", request_type: "OEM_ERRORS", equipment_id: 16, zone_id: null, start_time: null, end_time: null, parameters: [], reason: "Rechercher un signal OEM discriminant." }, outcome: "AVAILABLE", evidence_ids: ["ev-oem"], attempted_at: "2026-08-26T07:32:00Z" }],
    conclusion: {
      summary: conclusive ? "La dégradation thermique est l’explication la mieux étayée de l’arrêt." : "Available evidence is insufficient to determine a reliable root cause.",
      diagnosis_status: status,
      observed_condition: "TRK-016 s’est arrêté mécaniquement à 07:31.",
      root_cause: conclusive ? "Dégradation thermique du moteur" : null,
      reliable_root_cause: status === "CONFIRMED",
      causal_depth: conclusive ? 2 : 0,
      contributing_factors: conclusive ? [{ statement: "Baisse progressive de pression d’huile", evidence_ids: ["ev-trends"] }] : [],
      observed_fact_evidence_ids: ["ev-oem"],
      derived_metric_evidence_ids: ["ev-trends"],
      supported_hypothesis_ids: conclusive ? ["hyp-thermal"] : [],
      unresolved_uncertainties: conclusive ? ["The exact causal mechanism or failed component is not confirmed."] : ["Evidence cannot discriminate between competing hypotheses."],
      confidence: conclusive ? "HIGH" : "LOW",
    },
    recommendation: {
      action_type: "INSPECT_EQUIPMENT",
      description: "Inspecter le circuit de refroidissement avant remise en service.",
      rationale: "La hausse thermique précède l’arrêt.",
      evidence_ids: ["ev-trends"],
      target_equipment_id: 16,
      target_zone_id: null,
      operational_constraints: ["Consigner l’équipement avant inspection."],
      human_validation_required: true,
    },
  }
}

describe("InvestigationResultView operator report", () => {
  it.each([
    ["CONFIRMED", "Cause confirmée"],
    ["PROBABLE", "Cause probable"],
    ["INCONCLUSIVE", "Cause non déterminée"],
  ] as const)("renders %s diagnosis semantics", (status, label) => {
    const html = renderToStaticMarkup(createElement(InvestigationResultView, { result: mechanicalResult(status) }))
    expect(html).toContain(label)
    expect(html).toContain(status === "INCONCLUSIVE" ? "Confiance causale :" : "Dégradation thermique du moteur")
    if (status === "PROBABLE") {
      expect(html).toContain("Confirmation incomplète")
      expect(html).not.toContain("Cause confirmée")
    }
    if (status === "INCONCLUSIVE") expect(html).toContain("Les preuves disponibles ne permettent pas")
  })

  it("shows a bounded evidence summary with trends, directions, and no fabricated impact", () => {
    const html = renderToStaticMarkup(createElement(InvestigationResultView, { result: mechanicalResult() }))
    expect(html).toContain("Pourquoi MinePulse pense cela")
    expect(html).toContain("Température moteur")
    expect(html).toContain("89,8 → 105,6 °C")
    expect(html).toContain("Pression d’huile")
    expect(html).toContain("426 → 329,8 kPa")
    expect((html.match(/data-evidence-summary="true"/g) ?? [])).toHaveLength(4)
    expect(html).toContain("Impact non quantifié")
    expect(html).not.toMatch(/gain|économie|tonnes perdues/i)
  })

  it("keeps hypotheses, contradictions, process, and technical provenance collapsed by default", () => {
    const html = renderToStaticMarkup(createElement(InvestigationResultView, { result: mechanicalResult("INCONCLUSIVE") }))
    for (const id of ["hypotheses-detail", "uncertainty-detail", "technical-evidence"]) expect(html).toContain(`data-testid="${id}"`)
    expect(html).not.toMatch(/<details[^>]*\sopen(?:=|\s|>)/)
    expect(html).toContain("Hypothèses examinées")
    expect(html).toContain("Signaux contradictoires")
    expect(html).toContain("Processus d’investigation")
    expect(html).toContain("Données structurées et identifiants")
  })

  it("presents recommendation, uncertainty, causal story, and human validation prominently", () => {
    const html = renderToStaticMarkup(createElement(InvestigationResultView, { result: mechanicalResult() }))
    expect(html).toContain("Ce qui semble s’être passé")
    expect(html).toContain("Action recommandée")
    expect(html).toContain("Inspecter le circuit de refroidissement")
    expect(html).toContain("Le mécanisme causal exact ou le composant défaillant n’est pas confirmé")
    expect(html).toContain("Validation humaine requise")
    expect(html).toContain("aucune action automatique")
  })

  it("renders FAILED as execution failure with a safe refresh action, not as inconclusive", () => {
    const onRetry = vi.fn()
    const failed: InvestigationResult = { ...mechanicalResult(), status: "FAILED", conclusion: null, recommendation: null, error: { stage: "analyze", error_type: "ProviderTimeoutError", message: "secret provider payload" } }
    const html = renderToStaticMarkup(createElement(InvestigationResultView, { result: failed, onRetry }))
    expect(html).toContain("Analyse IA indisponible")
    expect(html).toContain("MinePulse n’a pas pu terminer")
    expect(html).toContain("Actualiser l’investigation")
    expect(html).not.toContain("Cause non déterminée")
    expect(html).not.toContain("secret provider payload")
  })

  it("keeps null operational values unavailable instead of displaying zero", () => {
    const html = renderToStaticMarkup(createElement(InvestigationResultView, { result: baseResult }))
    expect(html).toContain("Indisponible")
    expect(html).not.toMatch(/>0(?:&nbsp;|\s)*t</)
    expect(html).toContain("Impact non quantifié")
  })
})

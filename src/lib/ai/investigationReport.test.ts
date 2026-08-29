import { expect, it } from "vitest"

import {
  causalStorySteps,
  compactOperatorText,
  keyEvidence,
  operatorText,
  uniqueDisplayStrings,
} from "./investigationReport"
import type { InvestigationResult } from "@/lib/api/types/ai"
import { result as baseResult } from "@/test/aiFixtures"

function batteryResult(overrides: Partial<InvestigationResult> = {}): InvestigationResult {
  return {
    ...baseResult,
    trigger: {
      ...baseResult.trigger,
      trigger_type: "EQUIPMENT_ANOMALY",
      subject: "EQUIPMENT",
      equipment_id: 10,
      payload: { title: "TRK-010 tension batterie basse", category: "BATTERY_VOLTAGE_LOW" },
    },
    evidence: [
      {
        evidence_id: "ev-trends",
        kind: "DERIVED_METRIC",
        source_tool: "equipment_telemetry_trends",
        source_service: "app.oem.queries.get_equipment_signal_trends",
        metric: "equipment_telemetry_trends",
        value: {
          metrics: [
            { metric: "engine_temp_c", unit: "°C", sampleCount: 8, firstValue: 89.8, lastValue: 105.6, direction: "rising", lastObservedAt: "2026-08-26T07:04:00Z" },
            { metric: "coolant_temp_c", unit: "°C", sampleCount: 8, firstValue: 83.1, lastValue: 97.9, direction: "rising", lastObservedAt: "2026-08-26T07:04:00Z" },
            { metric: "oil_pressure_kpa", unit: "kPa", sampleCount: 8, firstValue: 426, lastValue: 329.8, direction: "falling", lastObservedAt: "2026-08-26T07:04:00Z" },
            { metric: "fuel_rate_lph", unit: "L/h", sampleCount: 8, firstValue: 42, lastValue: 48, direction: "rising", lastObservedAt: "2026-08-26T07:04:00Z" },
          ],
        },
        available: true,
        status: "AVAILABLE",
        unit: null,
        site_id: 17,
        shift_id: 29,
        equipment_id: 10,
        zone_id: null,
        observed_at: "2026-08-26T07:04:00Z",
        source_record_ids: ["equipment:10"],
        metadata: { preIncidentSampleCount: 8 },
        notes: null,
      },
      {
        evidence_id: "ev-oem",
        kind: "FACT",
        source_tool: "oem_errors",
        source_service: "app.oem.queries.error_codes",
        metric: "oem_error_codes",
        value: [{ errorCode: "SIM-BATT-VOLT-LOW", description: "Tension batterie basse", lastOccurrence: "2026-08-26T07:05:00Z" }],
        available: true,
        status: "AVAILABLE",
        unit: null,
        site_id: 17,
        shift_id: 29,
        equipment_id: 10,
        zone_id: null,
        observed_at: "2026-08-26T07:05:00Z",
        source_record_ids: ["event:81"],
        metadata: {},
        notes: null,
      },
    ],
    hypotheses: [{
      hypothesis_id: "hyp-batt",
      statement: "Anomalie probable de la batterie ou du système de charge",
      supporting_evidence_ids: ["ev-oem", "ev-trends"],
      contradictory_evidence_ids: [],
      confidence: "MEDIUM",
      causal_depth: 1,
      rationale: "Le code OEM électrique précède l’alerte.",
    }],
    conclusion: {
      summary: "Anomalie électrique basse tension affectant probablement la batterie ou le système de charge.",
      diagnosis_status: "PROBABLE",
      observed_condition: "TRK-010 — tension batterie sous le seuil attendu.",
      root_cause: "Anomalie probable de la batterie ou du système de charge",
      reliable_root_cause: false,
      causal_depth: 1,
      contributing_factors: [],
      observed_fact_evidence_ids: ["ev-oem"],
      derived_metric_evidence_ids: ["ev-trends"],
      supported_hypothesis_ids: ["hyp-batt"],
      unresolved_uncertainties: ["The exact causal mechanism or failed component is not confirmed."],
      confidence: "MEDIUM",
    },
    recommendation: {
      action_type: "INSPECT_EQUIPMENT",
      description: "Inspecter la batterie et le circuit de charge de TRK-010 avant remise en service.",
      rationale: "Le code OEM SIM-BATT-VOLT-LOW indique une anomalie électrique au moment de l’incident.",
      evidence_ids: ["ev-oem"],
      target_equipment_id: 10,
      target_zone_id: null,
      operational_constraints: ["Validation terrain requise"],
      human_validation_required: true,
    },
    ...overrides,
  }
}

it("maps known backend English strings and keeps canonical codes", () => {
  expect(operatorText("The exact causal mechanism or failed component is not confirmed.")).toContain("n’est pas confirmé")
  expect(operatorText("Inspecter TRK-010 et le code SIM-BATT-VOLT-LOW")).toContain("TRK-010")
  expect(operatorText("Inspecter TRK-010 et le code SIM-BATT-VOLT-LOW")).toContain("SIM-BATT-VOLT-LOW")
  expect(operatorText("TRK-010 — tension batterie sous seuil de simulation.")).toBe("TRK-010 — tension batterie sous le seuil attendu.")
})

it("prioritizes OEM electrical evidence over unrelated thermal telemetry", () => {
  const cards = keyEvidence(batteryResult())
  expect(cards[0]?.value).toBe("SIM-BATT-VOLT-LOW")
  expect(cards.some((card) => card.label === "Mesure électrique directe" && !card.available)).toBe(true)
  expect(cards.some((card) => card.label === "Température moteur")).toBe(false)
  expect(cards.some((card) => card.label === "Pression d’huile")).toBe(false)
  expect(cards.some((card) => card.value === "SIM-BATT-VOLT-LOW")).toBe(true)
})

it("surfaces missing electrical measurements when the diagnosis is electrical", () => {
  const withoutOem = batteryResult({
    evidence: batteryResult().evidence.filter((item) => item.evidence_id === "ev-trends"),
    hypotheses: [{ ...batteryResult().hypotheses[0], supporting_evidence_ids: ["ev-trends"] }],
    conclusion: { ...batteryResult().conclusion!, observed_fact_evidence_ids: [], supported_hypothesis_ids: ["hyp-batt"] },
  })
  const cards = keyEvidence(withoutOem)
  expect(cards.some((card) => card.label === "Mesure électrique directe" && !card.available)).toBe(true)
  expect(cards.some((card) => card.label === "Température moteur")).toBe(false)
})

it("keeps thermal and oil telemetry for a mechanical diagnosis", () => {
  const mechanical: InvestigationResult = {
    ...batteryResult(),
    trigger: { ...batteryResult().trigger, payload: { title: "Arrêt mécanique", category: "MECHANICAL_STOP" } },
    hypotheses: [{
      hypothesis_id: "hyp-thermal",
      statement: "Dégradation thermique du moteur",
      supporting_evidence_ids: ["ev-trends", "ev-oem"],
      contradictory_evidence_ids: [],
      confidence: "HIGH",
      causal_depth: 2,
      rationale: "Les tendances précèdent l’arrêt.",
    }],
    evidence: [
      ...batteryResult().evidence.filter((item) => item.evidence_id === "ev-trends"),
      {
        ...batteryResult().evidence[1],
        value: [{ errorCode: "SIM-ENG-TEMP-HIGH", description: "Température moteur élevée", lastOccurrence: "2026-08-26T07:24:00Z" }],
      },
    ],
    conclusion: {
      ...batteryResult().conclusion!,
      root_cause: "Dégradation thermique du moteur",
      observed_condition: "TRK-016 s’est arrêté mécaniquement à 07:31.",
      summary: "La dégradation thermique est l’explication la mieux étayée.",
      supported_hypothesis_ids: ["hyp-thermal"],
    },
  }
  const cards = keyEvidence(mechanical)
  expect(cards.some((card) => card.label === "Température moteur")).toBe(true)
  expect(cards.some((card) => card.label === "Pression d’huile")).toBe(true)
  expect(cards.some((card) => card.label === "Mesure électrique directe")).toBe(false)
})

it("does not build a circular electrical causal chain", () => {
  const circular = batteryResult({
    conclusion: {
      ...batteryResult().conclusion!,
      root_cause: "Condition électrique basse tension",
      observed_condition: "Tension batterie sous le seuil",
      causal_depth: 1,
    },
  })
  const steps = causalStorySteps(circular)
  expect(steps.join(" ")).toContain("SIM-BATT-VOLT-LOW")
  expect(steps.filter((step) => /tension|électrique/i.test(step)).length).toBeLessThan(3)
  expect(steps.join(" ")).toContain("n’est pas identifié")
})

it("deduplicates near-identical uncertainty strings", () => {
  expect(uniqueDisplayStrings([
    "The exact causal mechanism or failed component is not confirmed.",
    "Le mécanisme causal exact ou le composant défaillant n’est pas confirmé.",
  ])).toHaveLength(1)
})

it("keeps compact operator text to a short French sentence", () => {
  const compact = compactOperatorText("Anomalie électrique basse tension affectant probablement la batterie ou le système de charge. Détail inutilement long.")
  expect(compact).not.toContain("Détail inutilement long")
  expect(compact.length).toBeLessThan(180)
})

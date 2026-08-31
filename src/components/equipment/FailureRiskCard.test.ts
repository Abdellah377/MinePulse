import { createElement } from "react"
import { readFileSync } from "node:fs"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"
import { FailureRiskCard } from "@/components/equipment/FailureRiskCard"
import type { FailureRiskDto } from "@/lib/api/types/ops"
import {
  FAILURE_RISK_LOADING_COPY,
  FAILURE_RISK_PROTOTYPE_LABEL,
  FAILURE_RISK_SIGNALS_UNAVAILABLE,
  demoFailureRisk,
  failureRiskView,
  failureRiskWhy,
} from "@/lib/equipment/failureRisk"

function prediction(overrides: Partial<FailureRiskDto> = {}): FailureRiskDto {
  return {
    equipmentId: 10,
    equipmentCode: "TRK-010",
    predictionTimestamp: "2026-08-30T12:00:00+00:00",
    horizonMinutes: 60,
    riskProbability: 0.74,
    riskLevel: "HIGH",
    modelVersion: "failure_risk_v1",
    modelType: "logistic",
    servedPredictor: "logistic",
    threshold: 0.41,
    status: "AVAILABLE",
    dataClass: "synthetic_prototype",
    topPredictiveSignals: ["oil_pressure_kpa"],
    detail: null,
    ...overrides,
  }
}

it("shows current probability, backend risk level, and 60-minute window wording", () => {
  const html = renderToStaticMarkup(createElement(FailureRiskCard, { prediction: prediction() }))
  expect(html).toContain("74%")
  expect(html).toContain("Élevé")
  expect(html).toContain("dans les 60 prochaines minutes")
  expect(html).toContain("60")
  expect(html.toLowerCase()).not.toContain("will fail")
  expect(html.toLowerCase()).not.toContain("failure in 60 minutes")
  expect(html).toContain(FAILURE_RISK_PROTOTYPE_LABEL)
  expect(html).toContain("Pourquoi ?")
})

it("insufficient history and unavailable do not show a fake 0%", () => {
  const insufficient = renderToStaticMarkup(
    createElement(FailureRiskCard, {
      prediction: prediction({ status: "INSUFFICIENT_HISTORY", riskProbability: null, riskLevel: null }),
    })
  )
  expect(insufficient).toContain("Historique insuffisant pour prédire.")
  expect(insufficient).not.toContain("0%")

  const unavailable = renderToStaticMarkup(
    createElement(FailureRiskCard, {
      prediction: prediction({ status: "UNAVAILABLE", riskProbability: null, riskLevel: null }),
    })
  )
  expect(unavailable).toContain("Prédiction indisponible.")
  expect(unavailable).not.toContain("0%")
})

it("pending prediction shows a skeleton without a fake percentage", () => {
  const html = renderToStaticMarkup(createElement(FailureRiskCard, { loading: true }))
  expect(html).toContain(FAILURE_RISK_LOADING_COPY)
  expect(html).not.toContain("%")
  expect(html).not.toContain("0%")
  expect(html).not.toContain("74")
})

it("distinguishes loading, ready, unsupported, and error without treating null as loading forever", () => {
  expect(failureRiskView({
    apiMode: true, equipmentType: "haul_truck", loading: true, error: null, prediction: null,
  })).toEqual({ kind: "loading" })
  expect(failureRiskView({
    apiMode: true, equipmentType: "haul_truck", loading: false, error: null, prediction: prediction(),
  }).kind).toBe("ready")
  expect(failureRiskView({
    apiMode: true, equipmentType: "excavator", loading: true, error: null, prediction: null,
  })).toEqual({ kind: "hidden" })
  expect(failureRiskView({
    apiMode: true, equipmentType: "haul_truck", loading: false, error: "Impossible de charger le détail équipement.", prediction: null,
  }).kind).toBe("error")
})

it("Pourquoi ? uses supplied topSignals and stays honest when they are absent", () => {
  const withSignals = failureRiskWhy(prediction())
  expect(withSignals.signalsAvailable).toBe(true)
  expect(withSignals.signals[0]).toContain("Pression")
  expect(withSignals.probabilityLabel).toBe("74%")
  expect(withSignals.horizonMinutes).toBe(60)
  expect(withSignals.prototype).toBe(true)

  const empty = failureRiskWhy(prediction({ topPredictiveSignals: [] }))
  expect(empty.signalsAvailable).toBe(false)
  expect(FAILURE_RISK_SIGNALS_UNAVAILABLE).toContain("ne sont pas disponibles")
})

it("API-mode inspector does not import mock world generator for the score", () => {
  const source = readFileSync("src/components/equipment/EquipmentDetailContent.tsx", "utf8")
  expect(source).not.toMatch(/mock\/generator/)
  expect(source).toContain("useApiMode")
  expect(source).toContain("demoFailureRisk")
  expect(source).toMatch(/useApiMode\s*\?\s*apiFailureRisk/)
  const apercu = source.slice(source.indexOf('value="apercu"'), source.indexOf('value="cycle"'))
  const ia = source.slice(source.indexOf('value="ia"'))
  expect(apercu).not.toContain("FailureRiskCard")
  expect(ia).toContain("FailureRiskCard")
  expect(ia).toContain("loading")
  expect(source).toContain("Voir sur la carte")
  expect(source).toContain("openMapForTarget")
  expect(source).toContain("failureRiskView")
  expect(source).not.toMatch(/TabsContent value="ia"[\s\S]*fetchEquipmentDetail/)
})

it("Failure-Risk Pourquoi does not call LangGraph", () => {
  const card = readFileSync("src/components/equipment/FailureRiskCard.tsx", "utf8")
  expect(card).not.toContain("useInvestigationStore")
  expect(card).not.toContain("aiApi")
  expect(card).toContain("AiWhyButton")
  expect(readFileSync("src/lib/equipment/failureRisk.ts", "utf8")).not.toContain("buildPredictionIntelligence")
})

it("demo helper stays labeled prototype and is not a live API substitute", () => {
  const demo = demoFailureRisk("TRK-010")
  expect(demo.dataClass).toBe("synthetic_prototype")
  expect(demo.status).toBe("AVAILABLE")
  expect(demo.riskProbability).not.toBeNull()
})

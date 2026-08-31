import { createElement } from "react"
import { readFileSync } from "node:fs"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"
import { FailureRiskCard } from "@/components/equipment/FailureRiskCard"
import type { FailureRiskDto } from "@/lib/api/types/ops"
import {
  FAILURE_RISK_PROTOTYPE_LABEL,
  demoFailureRisk,
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
  expect(html).toContain("Pression d")
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
  expect(source).toContain("Voir sur la carte")
  expect(source).toContain("openMapForTarget")
})

it("demo helper stays labeled prototype and is not a live API substitute", () => {
  const demo = demoFailureRisk("TRK-010")
  expect(demo.dataClass).toBe("synthetic_prototype")
  expect(demo.status).toBe("AVAILABLE")
  expect(demo.riskProbability).not.toBeNull()
})

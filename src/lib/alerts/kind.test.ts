import { expect, it } from "vitest"
import type { Alert } from "@/lib/mock/types"
import { alertsForKind, filterAlertsByUi, isPredictionAlert, userInvestigateTriggerType } from "./kind"

const current: Alert = {
  id: "alert-1",
  severity: "warning",
  status: "new",
  title: "Arrêt inattendu",
  description: "Camion arrêté",
  equipmentId: "TRK-001",
  zoneId: "Z-1",
  location: "Banc A",
  category: "EQUIPMENT_ANOMALY",
  source: "RULE",
  createdAt: 2,
  updatedAt: 2,
  assignedTo: null,
  resolution: null,
}

const currentCritical: Alert = {
  ...current,
  id: "alert-3",
  severity: "critical",
  zoneId: "Z-2",
  title: "Perte de communication",
}

const prediction: Alert = {
  id: "alert-2",
  severity: "warning",
  status: "new",
  title: "Risque mécanique prédit — TRK-010",
  description: "Risque prédit élevé d'entrer en arrêt mécanique dans les 60 prochaines minutes.",
  equipmentId: "TRK-010",
  zoneId: "Z-1",
  location: "Banc A",
  category: "PREDICTED_MECHANICAL_FAILURE_RISK",
  source: "PREDICTION",
  createdAt: 1,
  updatedAt: 1,
  assignedTo: null,
  resolution: null,
}

const mixed = [current, currentCritical, prediction]

it("identifies prediction alerts from backend source, not title text", () => {
  expect(isPredictionAlert(prediction)).toBe(true)
  expect(isPredictionAlert(current)).toBe(false)
  expect(isPredictionAlert({ source: undefined })).toBe(false)
  expect(alertsForKind(mixed, "current")).toEqual([current, currentCritical])
  expect(alertsForKind(mixed, "prediction")).toEqual([prediction])
})

it("applies severity and zone filters within the selected tab only", () => {
  expect(filterAlertsByUi(mixed, "current", "all", "all")).toEqual([current, currentCritical])
  expect(filterAlertsByUi(mixed, "prediction", "all", "all")).toEqual([prediction])
  expect(filterAlertsByUi(mixed, "current", "warning", "all")).toEqual([current])
  expect(filterAlertsByUi(mixed, "prediction", "warning", "all")).toEqual([prediction])
  expect(filterAlertsByUi(mixed, "prediction", "critical", "all")).toEqual([])
  expect(filterAlertsByUi(mixed, "current", "all", "Z-1")).toEqual([current])
  expect(filterAlertsByUi(mixed, "prediction", "all", "Z-1")).toEqual([prediction])
  expect(filterAlertsByUi(mixed, "prediction", "all", "Z-2")).toEqual([])
})

it("preserves the prediction trigger type for user investigate", () => {
  expect(userInvestigateTriggerType(prediction)).toBe("PREDICTED_MECHANICAL_FAILURE_RISK")
  expect(userInvestigateTriggerType(current)).toBe("OPERATIONAL_EVENT")
})

import { expect, it } from "vitest"
import type { Alert } from "@/lib/mock/types"
import {
  alertNoticeHeadline,
  alertWorkspaceContext,
  diffNewAlerts,
  toAlertNotice,
} from "./notifications"

const current: Alert = {
  id: "alert-1",
  severity: "critical",
  status: "new",
  title: "Attente prolongée",
  description: "File d’attente inhabituelle au chargement.",
  equipmentId: "TRK-002",
  zoneId: "Z-1",
  location: "Banc A",
  category: "EQUIPMENT_ANOMALY",
  source: "RULE",
  createdAt: 1,
  updatedAt: 1,
  assignedTo: null,
  resolution: null,
}

const prediction: Alert = {
  ...current,
  id: "alert-pred",
  severity: "warning",
  title: "Risque mécanique prédit élevé",
  description: "Risque mécanique prédit élevé dans les 60 prochaines minutes.",
  equipmentId: "TRK-010",
  category: "PREDICTED_MECHANICAL_FAILURE_RISK",
  source: "PREDICTION",
}

it("does not emit notices for historical alerts present at first observation", () => {
  const first = diffNewAlerts(null, [current, prediction])
  expect(first.fresh).toEqual([])
  expect([...first.seen]).toEqual(["alert-1", "alert-pred"])
})

it("emits one notice for a newly arriving current alert and one for a prediction", () => {
  const seeded = diffNewAlerts(null, [current])
  const withPrediction = diffNewAlerts(seeded.seen, [current, prediction])
  expect(withPrediction.fresh).toEqual([prediction])
  const extra = { ...current, id: "alert-13", title: "Arrêt inattendu" }
  const withCurrent = diffNewAlerts(withPrediction.seen, [current, prediction, extra])
  expect(withCurrent.fresh).toEqual([extra])
})

it("does not re-emit when the same alert is polled again", () => {
  const seeded = diffNewAlerts(null, [current, prediction])
  const again = diffNewAlerts(seeded.seen, [
    { ...current, updatedAt: 99, status: "acknowledged" },
    { ...prediction, updatedAt: 99 },
  ])
  expect(again.fresh).toEqual([])
})

it("keeps prediction wording and opens the matching Alertes IA tab", () => {
  const notice = toAlertNotice(prediction)
  expect(notice.kind).toBe("prediction")
  expect(notice.title).toContain("Risque mécanique prédit")
  expect(notice.title.toLowerCase()).not.toContain("panne mécanique")
  expect(alertWorkspaceContext(prediction)).toMatchObject({
    alertId: "alert-pred",
    predictionId: "alert-pred",
  })
  expect(alertWorkspaceContext(current)).toMatchObject({
    alertId: "alert-1",
  })
  expect(alertWorkspaceContext(current).predictionId).toBeUndefined()
  expect(alertNoticeHeadline(current)).toBe("TRK-002 — Attente prolongée")
})

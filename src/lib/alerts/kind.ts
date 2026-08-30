import type { Alert } from "@/lib/mock/types"
import type { TriggerType } from "@/lib/api/types/ai"

export type AlertListKind = "current" | "prediction"

export function isPredictionAlert(alert: Pick<Alert, "source">): boolean {
  return alert.source === "PREDICTION"
}

export function alertsForKind<T extends Pick<Alert, "source">>(
  alerts: readonly T[],
  kind: AlertListKind,
): T[] {
  return alerts.filter((alert) => isPredictionAlert(alert) === (kind === "prediction"))
}

export function filterAlertsByUi<T extends Pick<Alert, "source" | "severity" | "zoneId">>(
  alerts: readonly T[],
  kind: AlertListKind,
  severity: string,
  zone: string,
): T[] {
  return alertsForKind(alerts, kind).filter(
    (alert) => (severity === "all" || alert.severity === severity) && (zone === "all" || alert.zoneId === zone),
  )
}

export function userInvestigateTriggerType(alert: Pick<Alert, "source" | "category">): TriggerType {
  if (isPredictionAlert(alert) && alert.category === "PREDICTED_MECHANICAL_FAILURE_RISK") {
    return "PREDICTED_MECHANICAL_FAILURE_RISK"
  }
  return "OPERATIONAL_EVENT"
}

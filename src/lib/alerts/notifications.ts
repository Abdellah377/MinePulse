import type { Alert, AlertSeverity } from "@/lib/mock/types"
import type { WorkspaceContext } from "@/lib/workspace/types"
import { isPredictionAlert } from "@/lib/alerts/kind"

export type AlertNotice = {
  id: string
  alertId: string
  title: string
  description: string
  severity: AlertSeverity
  kind: "current" | "prediction"
}

export function diffNewAlerts<T extends Pick<Alert, "id">>(
  seenIds: ReadonlySet<string> | null,
  alerts: readonly T[],
): { seen: Set<string>; fresh: T[] } {
  const currentIds = alerts.map((alert) => alert.id)
  if (seenIds == null) {
    return { seen: new Set(currentIds), fresh: [] }
  }
  const fresh = alerts.filter((alert) => !seenIds.has(alert.id))
  if (fresh.length === 0) {
    return { seen: seenIds instanceof Set ? seenIds : new Set(seenIds), fresh: [] }
  }
  const seen = new Set(seenIds)
  for (const alert of fresh) seen.add(alert.id)
  return { seen, fresh }
}

export function alertNoticeHeadline(
  alert: Pick<Alert, "title" | "equipmentId">,
  equipmentCode?: string | null,
): string {
  const code = equipmentCode || alert.equipmentId
  if (!code) return alert.title
  if (alert.title.includes(code)) return alert.title
  return `${code} — ${alert.title}`
}

export function alertWorkspaceContext(
  alert: Pick<Alert, "id" | "source" | "equipmentId" | "zoneId">,
  equipmentCode?: string | null,
): WorkspaceContext {
  const prediction = isPredictionAlert(alert)
  return {
    alertId: alert.id,
    predictionId: prediction ? alert.id : undefined,
    equipmentId: alert.equipmentId ?? undefined,
    equipmentCode: equipmentCode ?? alert.equipmentId ?? undefined,
    zoneId: alert.zoneId ?? undefined,
  }
}

export function toAlertNotice(
  alert: Pick<Alert, "id" | "title" | "description" | "severity" | "source" | "equipmentId">,
  equipmentCode?: string | null,
): AlertNotice {
  return {
    id: alert.id,
    alertId: alert.id,
    title: alertNoticeHeadline(alert, equipmentCode),
    description: alert.description,
    severity: alert.severity,
    kind: isPredictionAlert(alert) ? "prediction" : "current",
  }
}

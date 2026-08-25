import type { Alert, AlertSeverity, AlertStatus, Equipment, Zone } from "@/lib/mock/types"
import { ALERT_STATUS_LABEL } from "@/lib/mock/types"
import { investigateException } from "@/lib/ai/exceptionInvestigation"
import {
  getMerahPredictions,
  getPredictionById,
  type AiPrediction,
} from "@/lib/ai/predictions"
import { MERAH_SHIFT_SCENARIO } from "@/lib/mock/scenario"
import { useApiMode } from "@/lib/api/client"
import { timeAgo } from "@/lib/format"

export type AlertKind = "current" | "prediction"

export interface IntelligenceItem {
  id: string
  kind: AlertKind
  severity: AlertSeverity
  category: string
  title: string
  summary: string
  equipmentId: string | null
  equipmentCode: string | null
  zoneId: string | null
  zoneName: string | null
  timeLabel: string
  horizonMin: number | null
  confidence: number
  statusLabel: string
  alertStatus?: AlertStatus
  predictionStatus?: AiPrediction["status"]
  probableCause: string
  facts: string[]
  signals: string[]
  impact: string
  suggestedAction: string
  ifIgnored: string
  sourceAlert?: Alert
  sourcePrediction?: AiPrediction
}

export function buildCurrentIntelligence(
  alerts: Alert[],
  equipment: Equipment[],
  zones: Zone[]
): IntelligenceItem[] {
  const eqById = new Map(equipment.map((e) => [e.id, e]))
  const zoneById = new Map(zones.map((z) => [z.id, z]))

  return alerts
    .filter((a) => a.status !== "resolved")
    .map((alert) => {
      const eq = alert.equipmentId ? eqById.get(alert.equipmentId) : undefined
      const zone = alert.zoneId ? zoneById.get(alert.zoneId) : undefined
      const inv = investigateException(alert, eq?.code)
      return {
        id: alert.id,
        kind: "current" as const,
        severity: alert.severity,
        category: alert.category,
        title: alert.title,
        summary: alert.description,
        equipmentId: eq?.id ?? null,
        equipmentCode: eq?.code ?? null,
        zoneId: zone?.id ?? null,
        zoneName: zone?.name ?? alert.location,
        timeLabel: timeAgo(alert.createdAt),
        horizonMin: null,
        confidence: inv.confidence,
        statusLabel: ALERT_STATUS_LABEL[alert.status],
        alertStatus: alert.status,
        probableCause: inv.probableCause,
        facts: inv.facts,
        signals: [...inv.supporting, ...inv.contradictory.slice(0, 1)],
        impact: inv.impact,
        suggestedAction: inv.verification,
        ifIgnored: inv.ifIgnored,
        sourceAlert: alert,
      }
    })
    .sort((a, b) => {
      const order = { critical: 0, warning: 1, info: 2 }
      if (order[a.severity] !== order[b.severity]) return order[a.severity] - order[b.severity]
      return (b.sourceAlert?.createdAt ?? 0) - (a.sourceAlert?.createdAt ?? 0)
    })
}

export function buildPredictionIntelligence(): IntelligenceItem[] {
  if (useApiMode) return []
  const S = MERAH_SHIFT_SCENARIO
  return getMerahPredictions().map((p) => ({
    id: p.id,
    kind: "prediction" as const,
    severity: p.severity,
    category: p.category,
    title: p.title,
    summary: p.summary,
    equipmentId: null,
    equipmentCode: p.equipmentCode,
    zoneId: null,
    zoneName: p.zoneName,
    timeLabel: `dans ${p.horizonMin} min`,
    horizonMin: p.horizonMin,
    confidence: p.confidence,
    statusLabel: p.status === "escalade" ? "Escalade" : "Surveillance",
    predictionStatus: p.status,
    probableCause: p.probableCause,
    facts: p.signals.slice(0, 2),
    signals: p.signals,
    impact: p.impact,
    suggestedAction: p.suggestedAction,
    ifIgnored: S.narrative.next,
    sourcePrediction: p,
  }))
}

export function getIntelligenceItem(
  id: string,
  alerts: Alert[],
  equipment: Equipment[],
  zones: Zone[]
): IntelligenceItem | null {
  const pred = getPredictionById(id)
  if (pred) return buildPredictionIntelligence().find((i) => i.id === id) ?? null
  return (
    buildCurrentIntelligence(alerts, equipment, zones).find((i) => i.id === id) ?? null
  )
}

export function actionsContextFromItem(item: IntelligenceItem) {
  return {
    alertId: item.kind === "current" ? item.id : undefined,
    predictionId: item.kind === "prediction" ? item.id : undefined,
    equipmentId: item.equipmentId ?? undefined,
    equipmentCode: item.equipmentCode ?? undefined,
    zoneId: item.zoneId ?? undefined,
    zoneName: item.zoneName ?? undefined,
    investigationId: `inv-${item.id}`,
    titleFocus: item.zoneName ?? item.equipmentCode ?? item.category,
  }
}

import type { Alert } from "@/lib/mock/types"
import type { InvestigationTriggerInput } from "@/lib/api/types/ai"
import { userInvestigateTriggerType } from "@/lib/alerts/kind"
import { operationalAlertTime } from "@/lib/alerts/order"

export function buildUserInvestigateTrigger(input: {
  siteId: number
  shiftId?: number | null
  alert: Pick<Alert, "id" | "source" | "category" | "title" | "description" | "severity"> & { createdAt?: number; occurredAt?: number | null }
  equipmentDatabaseId?: number | null
  zoneDatabaseId?: number | null
  source?: string | null
}): InvestigationTriggerInput {
  const { alert } = input
  const occurred = "createdAt" in alert || "occurredAt" in alert
    ? operationalAlertTime({ createdAt: alert.createdAt ?? Date.now(), occurredAt: alert.occurredAt })
    : Date.now()
  return {
    site_id: input.siteId,
    shift_id: input.shiftId,
    trigger_type: userInvestigateTriggerType(alert),
    trigger_source: "USER_INVESTIGATE",
    source: input.source ?? "alertes-ui",
    source_record_id: alert.id,
    equipment_id: input.equipmentDatabaseId ?? undefined,
    zone_id: input.zoneDatabaseId ?? undefined,
    occurred_at: new Date(occurred).toISOString(),
    severity: alert.severity === "critical" ? "CRITICAL" : alert.severity === "warning" ? "WARNING" : "INFO",
    payload: { category: alert.category, title: alert.title, description: alert.description },
  }
}

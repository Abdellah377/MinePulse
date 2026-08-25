/** MinePulse REST client — used when VITE_USE_API=true */

import type {
  Alert,
  AlertStatus,
  CycleTimeSample,
  DowntimeReason,
  Equipment,
  Operator,
  RoutePath,
  Shift,
  Site,
  TimelineSegment,
  Zone,
} from "@/lib/mock/types"
import type { ProductionByShift } from "@/lib/production/mergeProduction"

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api"
const DEFAULT_TIMEOUT_MS = 15_000

export type OpsContext = { siteCode?: string; shiftId?: string }

export type OperationalSettingsDto = {
  idle_alert_threshold_min: number
  no_comm_threshold_min: number
  cycle_duration_threshold_min: number
  oem_online_sec: number
  oem_disconnected_sec: number
}

export function opsQueryString(
  ctx?: OpsContext,
  extra?: Record<string, string | boolean | undefined>
): string {
  const params = new URLSearchParams()
  if (ctx?.siteCode) params.set("site_code", ctx.siteCode)
  if (ctx?.shiftId) params.set("shift_id", ctx.shiftId)
  if (extra) {
    for (const [k, v] of Object.entries(extra)) {
      if (v !== undefined && v !== false) params.set(k, String(v))
    }
  }
  const q = params.toString()
  return q ? `?${q}` : ""
}

export async function fetchJson<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const timeoutMs = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const { timeoutMs: _ignored, ...rest } = init ?? {}
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: {
        Accept: "application/json",
        ...(rest.body ? { "Content-Type": "application/json" } : {}),
        ...rest.headers,
      },
      signal: controller.signal,
    })
    if (!res.ok) {
      throw new Error(`API ${path}: ${res.status} ${res.statusText}`)
    }
    return res.json() as Promise<T>
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`API ${path}: timeout after ${timeoutMs}ms`)
    }
    throw err
  } finally {
    window.clearTimeout(timer)
  }
}

export interface BootstrapPayload {
  sites: Site[]
  shifts: Shift[]
  zones: Zone[]
  routes: RoutePath[]
  equipment: Equipment[]
  operators: Operator[]
  alerts: Alert[]
  productionByShift?: ProductionByShift
  timelineSegments: TimelineSegment[]
  cycleTimeSamples: CycleTimeSample[]
  downtimeReasons: DowntimeReason[]
  simNow?: string | null
  simulation?: Record<string, unknown>
  activeSiteCode?: string | null
  activeShiftId?: string | null
  error?: string
}

export function fetchBootstrap(options?: { lite?: boolean; ctx?: OpsContext }): Promise<BootstrapPayload> {
  const lite = options?.lite ? { lite: true } : undefined
  return fetchJson(`/bootstrap${opsQueryString(options?.ctx, lite)}`)
}

export function fetchEquipmentLive(ctx?: OpsContext): Promise<BootstrapPayload["equipment"]> {
  return fetchJson(`/equipment/live${opsQueryString(ctx)}`)
}

export function fetchOperationalSettings(): Promise<OperationalSettingsDto> {
  return fetchJson("/settings/operational")
}

export function patchOperationalSettings(
  patch: Partial<OperationalSettingsDto>
): Promise<OperationalSettingsDto> {
  return fetchJson("/settings/operational", {
    method: "PATCH",
    body: JSON.stringify(patch),
  })
}

export function patchAlert(
  alertId: string,
  body: { status?: AlertStatus; assigned_to_operator_id?: number; actor_label?: string; resolution?: string },
  ctx?: OpsContext
): Promise<Alert> {
  return fetchJson(`/alerts/${encodeURIComponent(alertId)}${opsQueryString(ctx)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
}

export function createZone(
  body: {
    code: string
    name: string
    type: string
    points: { x: number; y: number }[]
    color?: string
    description?: string
    capacity?: number
  },
  ctx?: OpsContext
): Promise<Zone> {
  return fetchJson(`/zones${opsQueryString(ctx)}`, {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export function patchZone(
  code: string,
  body: Partial<{
    name: string
    type: string
    points: { x: number; y: number }[]
    color: string
    description: string
    capacity: number
  }>,
  ctx?: OpsContext
): Promise<Zone> {
  return fetchJson(`/zones/${encodeURIComponent(code)}${opsQueryString(ctx)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
}

export function deleteZone(code: string, ctx?: OpsContext): Promise<{ ok: boolean }> {
  return fetchJson(`/zones/${encodeURIComponent(code)}${opsQueryString(ctx)}`, {
    method: "DELETE",
  })
}

export type EquipmentMaintenanceRow = {
  id: string
  date: number
  type: string
  durationH: number
  technician: string
}

export type EquipmentDetailPayload = {
  equipment: Equipment
  maintenanceHistory: EquipmentMaintenanceRow[]
}

export function fetchEquipmentDetail(
  code: string,
  ctx?: OpsContext
): Promise<EquipmentDetailPayload> {
  return fetchJson(`/equipment/${encodeURIComponent(code)}/detail${opsQueryString(ctx)}`)
}

export function fetchSimulationStatus(): Promise<Record<string, unknown>> {
  return fetchJson("/simulation/status")
}

export const useApiMode = import.meta.env.VITE_USE_API === "true"

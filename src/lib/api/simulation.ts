/** Typed client for Centre de simulation API */

const API = import.meta.env.VITE_API_BASE ?? "/api"

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}/simulation${path}`, {
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers },
    ...init,
  })
  if (!res.ok) throw new Error(`${path}: ${res.status}`)
  return res.json() as Promise<T>
}

export type SimStatus = {
  status: string
  speed: number
  mode: string
  seed: number
  scenario: string
  sim_now: string
  note?: string
  engine_alive?: boolean
  last_heartbeat_age_sec?: number | null
  embedded?: boolean
  tick_thread_alive?: boolean
  last_error?: string | null
  runtime?: {
    injections: Array<Record<string, unknown>>
    zone_queues: Record<string, { queue: string[]; occupants: string[]; capacity: number }>
    truck_count: number
  }
}

export type SimEquipmentRow = {
  code: string
  type: string
  state?: string
  speed_kmh?: number
  payload_t?: number
  fuel_pct?: number
  comm_lost?: boolean
  origin?: string
  dest?: string
  loader?: string
  road?: string
  capacity_factor?: number
  zone?: string
}

export type SimLogRow = {
  ts: string
  kind: string
  message: string
  target_type?: string
  target_id?: string
}

export type PropagationStatus = {
  target: string
  command_status?: string | null
  active_command_id?: string | null
  failure_stage?: string | null
  failure_reason?: string | null
  runtime?: Record<string, unknown>
  db_current_state?: string | null
  open_state_interval?: Record<string, unknown>
  active_injections?: Array<Record<string, unknown>>
  open_alerts?: Array<Record<string, unknown>>
  last_events?: Array<Record<string, unknown>>
  checks: Record<string, boolean>
}

export const simApi = {
  status: () => json<SimStatus>("/status"),
  start: () => json<SimStatus>("/start", { method: "POST" }),
  pause: () => json<SimStatus>("/pause", { method: "POST" }),
  resume: () => json<SimStatus>("/resume", { method: "POST" }),
  reset: () => json<SimStatus>("/reset", { method: "POST" }),
  setSpeed: (speed: number) =>
    json<SimStatus>("/speed", { method: "POST", body: JSON.stringify({ speed }) }),
  setMode: (mode: string) =>
    json<SimStatus>("/mode", { method: "POST", body: JSON.stringify({ mode }) }),
  equipment: () => json<SimEquipmentRow[]>("/equipment"),
  equipmentDetail: (code: string) => json<Record<string, unknown>>(`/equipment/${code}`),
  zones: () => json<Array<Record<string, unknown>>>("/zones"),
  roads: () => json<Array<Record<string, unknown>>>("/roads"),
  injections: () =>
    json<{ active: Array<Record<string, unknown>>; commands: Array<Record<string, unknown>> }>(
      "/injections"
    ),
  log: (limit = 80) => json<SimLogRow[]>(`/log?limit=${limit}`),
  inject: (body: {
    target_type: string
    target_id: string
    action: string
    parameters?: Record<string, unknown>
    duration_sec?: number | null
  }) => json("/inject", { method: "POST", body: JSON.stringify(body) }),
  cancelInjection: (commandId: string) =>
    json(`/injections/${commandId}`, { method: "DELETE" }),
  propagation: (code: string) => json<PropagationStatus>(`/propagation/${encodeURIComponent(code)}`),
}

export const SPEED_OPTIONS = [1, 5, 10, 30, 60, 120] as const

export const DURATION_OPTIONS: { label: string; seconds: number | null }[] = [
  { label: "Jusqu'à restauration", seconds: null },
  { label: "5 min sim", seconds: 5 * 60 },
  { label: "10 min sim", seconds: 10 * 60 },
  { label: "30 min sim", seconds: 30 * 60 },
  { label: "1 h sim", seconds: 60 * 60 },
]

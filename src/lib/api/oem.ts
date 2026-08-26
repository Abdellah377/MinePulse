import { fetchJson, opsQueryString, useApiMode, type OpsContext } from "@/lib/api/client"

export type OemCatalog = {
  sensors: Array<{
    key: string
    label_fr: string
    unit: string
    category: string
    source: string
    precision: number
    available_for: string[]
    threshold: {
      warnLow: number | null
      warnHigh: number | null
      critLow: number | null
      critHigh: number | null
      source: string
    } | null
  }>
  categories: Record<string, string>
  tyrePositions: Array<{ code: string; labelFr: string }>
  errorCodes: Array<{ code: string; category: string; severity: string; label: string }>
  thresholdSource: string
}

function oemGet<T>(path: string): Promise<T> {
  if (!useApiMode) {
    return Promise.reject(new Error("OEM requires API mode"))
  }
  return fetchJson(path)
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== "") u.set(k, String(v))
  }
  const s = u.toString()
  return s ? `?${s}` : ""
}

export function scopedOemApi(ctx?: OpsContext) {
  const get = <T>(path: string): Promise<T> => {
    if (/[?&](from|to)=unavailable(?:&|$)/.test(path)) return Promise.reject(new Error("Période non renseignée. Sélectionnez une fenêtre valide."))
    const context = opsQueryString(ctx).slice(1)
    return oemGet<T>(`${path}${context ? `${path.includes("?") ? "&" : "?"}${context}` : ""}`)
  }
  return {
  catalog: () => get<OemCatalog>("/oem/catalog"),
  connectivity: (from?: string, to?: string, siteCode?: string) =>
    get<{ rows: Record<string, unknown>[] }>(`/oem/connectivity${qs({ from, to, site_code: siteCode })}`),
  delays: (minDelaySec: number, from?: string, to?: string, siteCode?: string) =>
    get<{ rows: Record<string, unknown>[] }>(
      `/oem/connectivity/delays${qs({ from, to, min_delay_sec: minDelaySec, site_code: siteCode })}`
    ),
  ping: (code: string, from?: string, to?: string, siteCode?: string) =>
    get<Record<string, unknown>>(
      `/oem/connectivity/${encodeURIComponent(code)}/ping${qs({ from, to, site_code: siteCode })}`
    ),
  pingFleet: (codes: string, from?: string, to?: string, siteCode?: string) =>
    get<{ from: string; to: string; rows: Array<Record<string, unknown>> }>(
      `/oem/connectivity/ping${qs({ codes, from, to, site_code: siteCode })}`
    ),
  telemetry: (code: string, signals: string, from?: string, to?: string) =>
    get<Record<string, unknown>>(
      `/oem/equipment/${encodeURIComponent(code)}/telemetry${qs({ from, to, signals })}`
    ),
  tyres: (code: string, from?: string, to?: string, positions?: string) =>
    get<Record<string, unknown>>(
      `/oem/equipment/${encodeURIComponent(code)}/tyres${qs({ from, to, positions })}`
    ),
  diagnostic: (opts: Record<string, string | undefined>) =>
    get<{ rows: Record<string, unknown>[] }>(`/oem/diagnostic${qs(opts)}`),
  errors: (opts: Record<string, string | undefined>) =>
    get<{ rows: Record<string, unknown>[] }>(`/oem/errors${qs(opts)}`),
  maintenance: (opts: Record<string, string | undefined>) =>
    get<{ rows: Record<string, unknown>[] }>(`/oem/maintenance-indicators${qs(opts)}`),
  anomalies: (opts: Record<string, string | undefined>) =>
    get<{ rows: Record<string, unknown>[] }>(`/oem/anomalies${qs(opts)}`),
}
}

export const oemApi = scopedOemApi()

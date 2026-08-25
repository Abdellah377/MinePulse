import { useCallback, useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Check, Loader2, Pause, Play, RotateCcw, ShieldAlert, X } from "lucide-react"

import {
  DURATION_OPTIONS,
  SPEED_OPTIONS,
  simApi,
  type PropagationStatus,
  type SimEquipmentRow,
  type SimLogRow,
  type SimStatus,
} from "@/lib/api/simulation"
import { fetchBootstrap } from "@/lib/api/client"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

type AssetTab = "equipment" | "zones" | "roads"

function formatSimClock(iso?: string) {
  if (!iso) return "—"
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
  } catch {
    return iso
  }
}

export default function SimulationCentre() {
  const [status, setStatus] = useState<SimStatus | null>(null)
  const [equipment, setEquipment] = useState<SimEquipmentRow[]>([])
  const [zones, setZones] = useState<Record<string, unknown>[]>([])
  const [roads, setRoads] = useState<Record<string, unknown>[]>([])
  const [log, setLog] = useState<SimLogRow[]>([])
  const [injections, setInjections] = useState<Record<string, unknown>[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [tab, setTab] = useState<AssetTab>("equipment")
  const [search, setSearch] = useState("")
  const [typeFilter, setTypeFilter] = useState("all")
  const [selected, setSelected] = useState<string | null>(null)
  const [durationSec, setDurationSec] = useState<number | null>(30 * 60)
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null)
  const [propagation, setPropagation] = useState<PropagationStatus | null>(null)

  const hydrateWorld = useOpsStore((s) => s.hydrateWorld)

  const refresh = useCallback(async () => {
    try {
      const [st, eq, zn, rd, inj, lg] = await Promise.all([
        simApi.status(),
        simApi.equipment(),
        simApi.zones(),
        simApi.roads(),
        simApi.injections(),
        simApi.log(100),
      ])
      setStatus(st)
      setEquipment(eq)
      setZones(zn)
      setRoads(rd)
      setInjections(inj.active ?? [])
      setLog(lg)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "API simulation indisponible")
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => void refresh(), 1500)
    return () => window.clearInterval(id)
  }, [refresh])

  useEffect(() => {
    if (!selected) {
      setPropagation(null)
      return
    }
    const load = () => {
      void simApi.propagation(selected).then(setPropagation).catch(() => setPropagation(null))
    }
    load()
    const id = window.setInterval(load, 2000)
    return () => window.clearInterval(id)
  }, [selected, injections, equipment])

  async function refreshOpsStore() {
    try {
      const payload = await fetchBootstrap({ lite: true })
      if (!payload.error) hydrateWorld(payload)
    } catch {
      /* ops refresh best-effort */
    }
  }

  useEffect(() => {
    if (!selected || tab !== "equipment") {
      setDetail(null)
      return
    }
    void simApi
      .equipmentDetail(selected)
      .then(setDetail)
      .catch(() => setDetail(null))
  }, [selected, tab, equipment])

  const filteredEq = useMemo(() => {
    return equipment.filter((e) => {
      if (typeFilter !== "all" && e.type !== typeFilter) return false
      if (search && !e.code.toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }, [equipment, search, typeFilter])

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    try {
      await action()
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action échouée")
    } finally {
      setBusy(false)
    }
  }

  async function inject(target_type: string, target_id: string, action: string, parameters: Record<string, unknown> = {}) {
    await run(() =>
      simApi.inject({
        target_type,
        target_id,
        action,
        parameters,
        duration_sec: durationSec,
      })
    )
    await refreshOpsStore()
  }

  const engineOnline = status?.engine_alive ?? false

  const selectedEq = equipment.find((e) => e.code === selected)

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      {/* Test banner */}
      <div className="flex items-center gap-2 border-b border-amber-300/60 bg-amber-50 px-4 py-2 text-[12px] text-amber-950">
        <ShieldAlert className="size-3.5 shrink-0 text-amber-700" />
        <span className="font-semibold uppercase tracking-wide">Environnement de test</span>
        <span className="text-amber-800/80">
          Centre de simulation — ne contrôle pas d&apos;équipement réel. Mode simulation uniquement.
        </span>
        <Link to="/alertes" className="ml-auto text-amber-900 underline-offset-2 hover:underline">
          Retour ops
        </Link>
      </div>

      {/* Control header */}
      <header className="border-b border-border bg-surface px-4 py-3">
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <h1 className="text-base font-semibold tracking-tight text-foreground">Centre de simulation</h1>
          <Badge
            variant="outline"
            className={cn(
              "rounded-md",
              status?.status === "RUNNING" && "border-emerald-500/40 bg-emerald-50 text-emerald-800",
              status?.status === "PAUSED" && "border-amber-500/40 bg-amber-50 text-amber-900",
              status?.status === "STOPPED" && "border-border text-muted"
            )}
          >
            {status?.status ?? "…"}
          </Badge>
          <span className="text-[12px] text-muted">
            Sim <strong className="text-foreground">{formatSimClock(status?.sim_now)}</strong>
          </span>
          <span className="text-[12px] text-muted">
            Mode <strong className="text-foreground">{status?.mode ?? "—"}</strong>
          </span>
          <span className="text-[12px] text-muted">
            Seed <strong className="text-foreground">{status?.seed ?? "—"}</strong>
          </span>
          <Badge
            variant="outline"
            className={cn(
              "rounded-md text-[10px]",
              engineOnline ? "border-emerald-500/40 text-emerald-800" : "border-red-400/50 text-red-700"
            )}
          >
            Moteur {engineOnline ? "en ligne" : "hors ligne"}
          </Badge>
          {busy ? <Loader2 className="size-3.5 animate-spin text-muted" /> : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={busy} onClick={() => run(() => simApi.start())}>
            <Play className="size-3.5" /> Start
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => run(() => simApi.pause())}>
            <Pause className="size-3.5" /> Pause
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => run(() => simApi.resume())}>
            Resume
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => run(() => simApi.reset())}>
            <RotateCcw className="size-3.5" /> Reset
          </Button>

          <div className="mx-1 h-5 w-px bg-border" />

          <span className="text-[11px] text-muted">Vitesse</span>
          <Select
            value={String(status?.speed ?? 30)}
            onValueChange={(v) => run(() => simApi.setSpeed(Number(v)))}
          >
            <SelectTrigger className="h-8 w-[5.5rem]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SPEED_OPTIONS.map((s) => (
                <SelectItem key={s} value={String(s)}>
                  ×{s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <span className="text-[11px] text-muted">Mode</span>
          <Select
            value={status?.mode ?? "MANUAL"}
            onValueChange={(v) => run(() => simApi.setMode(v))}
          >
            <SelectTrigger className="h-8 w-[8rem]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="MANUAL">MANUAL</SelectItem>
              <SelectItem value="NORMAL">NORMAL</SelectItem>
              <SelectItem value="STRESS">STRESS</SelectItem>
              <SelectItem value="SCENARIO">SCENARIO</SelectItem>
              <SelectItem value="REPLAY">REPLAY</SelectItem>
            </SelectContent>
          </Select>

          <span className="text-[11px] text-muted">Durée injection</span>
          <Select
            value={durationSec === null ? "null" : String(durationSec)}
            onValueChange={(v) => setDurationSec(v === "null" ? null : Number(v))}
          >
            <SelectTrigger className="h-8 w-[11rem]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DURATION_OPTIONS.map((d) => (
                <SelectItem key={d.label} value={d.seconds === null ? "null" : String(d.seconds)}>
                  {d.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {error ? (
          <p className="mt-2 text-[11px] text-danger">
            {error} — lancez <code className="font-mono">npm run dev:all</code> (API + simulateur intégré)
          </p>
        ) : null}
        {status?.note ? <p className="mt-1 text-[10px] text-muted-2">{status.note}</p> : null}
      </header>

      {/* Main 3-column layout */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 lg:grid-cols-[280px_1fr_320px]">
        {/* Left: asset list */}
        <aside className="flex min-h-0 flex-col border-r border-border bg-surface">
          <Tabs value={tab} onValueChange={(v) => setTab(v as AssetTab)} className="flex min-h-0 flex-1 flex-col">
            <TabsList className="m-2 grid w-auto grid-cols-3">
              <TabsTrigger value="equipment">Équip.</TabsTrigger>
              <TabsTrigger value="zones">Zones</TabsTrigger>
              <TabsTrigger value="roads">Routes</TabsTrigger>
            </TabsList>

            <TabsContent value="equipment" className="mt-0 flex min-h-0 flex-1 flex-col px-2 pb-2">
              <div className="mb-2 flex gap-2">
                <Input
                  placeholder="TRK-…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="h-8"
                />
                <Select value={typeFilter} onValueChange={setTypeFilter}>
                  <SelectTrigger className="h-8 w-[7rem]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tous</SelectItem>
                    <SelectItem value="HAUL_TRUCK">Camions</SelectItem>
                    <SelectItem value="EXCAVATOR">Pelles</SelectItem>
                    <SelectItem value="LOADER">Chargeuses</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto rounded-md border border-border/80">
                {filteredEq.map((e) => (
                  <button
                    key={e.code}
                    type="button"
                    onClick={() => setSelected(e.code)}
                    className={cn(
                      "flex w-full flex-col gap-0.5 border-b border-border/60 px-2.5 py-2 text-left text-[11px] hover:bg-surface-2",
                      selected === e.code && "bg-accent/10"
                    )}
                  >
                    <span className="font-semibold text-foreground">{e.code}</span>
                    <span className="text-muted">
                      {e.state ?? "—"}
                      {e.origin && e.dest ? ` · ${e.origin} → ${e.dest}` : e.zone ? ` · ${e.zone}` : ""}
                    </span>
                  </button>
                ))}
              </div>
            </TabsContent>

            <TabsContent value="zones" className="mt-0 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
              {zones.map((z) => (
                <button
                  key={String(z.code)}
                  type="button"
                  onClick={() => setSelected(String(z.code))}
                  className={cn(
                    "mb-1 w-full rounded-md border border-border/70 px-2.5 py-2 text-left text-[11px] hover:bg-surface-2",
                    selected === z.code && "border-accent/40 bg-accent/10"
                  )}
                >
                  <div className="font-semibold">{String(z.name)}</div>
                  <div className="text-muted">
                    cap {String(z.capacity)}/{String(z.base_capacity)} · file {(z.queue as string[])?.length ?? 0}
                  </div>
                </button>
              ))}
            </TabsContent>

            <TabsContent value="roads" className="mt-0 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
              {roads.map((r) => (
                <button
                  key={String(r.code)}
                  type="button"
                  onClick={() => setSelected(String(r.code))}
                  className={cn(
                    "mb-1 w-full rounded-md border border-border/70 px-2.5 py-2 text-left text-[11px] hover:bg-surface-2",
                    selected === r.code && "border-accent/40 bg-accent/10"
                  )}
                >
                  <div className="font-semibold">{String(r.code)}</div>
                  <div className="text-muted">
                    {String(r.from_zone)} → {String(r.to_zone)} · {r.closed ? "FERMÉE" : `${r.speed_limit} km/h`}
                  </div>
                </button>
              ))}
            </TabsContent>
          </Tabs>
        </aside>

        {/* Center: inspector + inject */}
        <section className="min-h-0 overflow-y-auto p-4">
          {!selected ? (
            <p className="text-sm text-muted">Sélectionnez un équipement, une zone ou une route.</p>
          ) : tab === "equipment" && selectedEq ? (
            <div className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold">{selectedEq.code}</h2>
                <p className="text-[12px] text-muted">{selectedEq.type}</p>
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px] sm:grid-cols-3">
                <div>
                  <dt className="text-muted">État</dt>
                  <dd className="font-medium">{detail?.phase ? String(detail.phase) : selectedEq.state}</dd>
                </div>
                <div>
                  <dt className="text-muted">Vitesse</dt>
                  <dd className="font-medium">{Number(detail?.speed_kmh ?? selectedEq.speed_kmh ?? 0).toFixed(1)} km/h</dd>
                </div>
                <div>
                  <dt className="text-muted">Payload</dt>
                  <dd className="font-medium">{Number(detail?.payload_t ?? selectedEq.payload_t ?? 0).toFixed(1)} t</dd>
                </div>
                <div>
                  <dt className="text-muted">Fuel</dt>
                  <dd className="font-medium">{Number(detail?.fuel_pct ?? selectedEq.fuel_pct ?? 0).toFixed(1)} %</dd>
                </div>
                <div>
                  <dt className="text-muted">Comm</dt>
                  <dd className="font-medium">{detail?.comm_lost || selectedEq.comm_lost ? "PERDUE" : "OK"}</dd>
                </div>
                <div>
                  <dt className="text-muted">Route</dt>
                  <dd className="font-medium">{String(detail?.road ?? selectedEq.road ?? "—")}</dd>
                </div>
              </dl>

              <div className="rounded-lg border border-border bg-surface p-3">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">Injections de test</p>
                {selectedEq.type === "HAUL_TRUCK" ? (
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "STOP_UNDEFINED")}>
                      STOP_UNDEFINED
                    </Button>
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "MECHANICAL_BREAKDOWN")}>
                      MECHANICAL_BREAKDOWN
                    </Button>
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "COMMUNICATION_LOSS")}>
                      COMMUNICATION_LOSS
                    </Button>
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "HIGH_ENGINE_TEMPERATURE")}>
                      HIGH_ENGINE_TEMPERATURE
                    </Button>
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "LOW_OIL_PRESSURE")}>
                      LOW_OIL_PRESSURE
                    </Button>
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "BATTERY_VOLTAGE_LOW")}>
                      BATTERY_VOLTAGE_LOW
                    </Button>
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "FUEL_RATE_HIGH")}>
                      FUEL_RATE_HIGH
                    </Button>
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "TYRE_PRESSURE_LOW")}>
                      TYRE_PRESSURE_LOW
                    </Button>
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "TYRE_TEMPERATURE_HIGH")}>
                      TYRE_TEMPERATURE_HIGH
                    </Button>
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "SENSOR_SIGNAL_LOSS")}>
                      SENSOR_SIGNAL_LOSS
                    </Button>
                    <Button size="sm" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "RESTORE")}>
                      RESTORE
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "MECHANICAL_BREAKDOWN")}>
                      BREAKDOWN
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!engineOnline || busy}
                      onClick={() =>
                        inject("EQUIPMENT", selectedEq.code, "REDUCED_CAPACITY", { capacity_factor: 0.5 })
                      }
                    >
                      REDUCED_CAPACITY 50%
                    </Button>
                    <Button size="sm" disabled={!engineOnline || busy} onClick={() => inject("EQUIPMENT", selectedEq.code, "RESTORE")}>
                      RESTORE
                    </Button>
                  </div>
                )}
                {!engineOnline ? (
                  <p className="mt-2 text-[10px] text-amber-800">
                    Moteur hors ligne — vérifiez que l&apos;API tourne (<code className="font-mono">npm run dev:all</code>),
                    puis cliquez Start.
                  </p>
                ) : null}
              </div>
            </div>
          ) : tab === "zones" ? (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">{selected}</h2>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => inject("ZONE", selected, "CLOSE_ZONE")}>
                  CLOSE_ZONE
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => inject("ZONE", selected, "REDUCE_CAPACITY", { capacity: 1 })}
                >
                  REDUCE_CAPACITY → 1
                </Button>
                <Button size="sm" onClick={() => inject("ZONE", selected, "RESTORE")}>
                  RESTORE
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">{selected}</h2>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => inject("ROAD", selected, "CLOSE_ROAD")}>
                  CLOSE_ROAD
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => inject("ROAD", selected, "CHANGE_SPEED_LIMIT", { speed_limit_kmh: 15 })}
                >
                  SPEED_LIMIT 15
                </Button>
                <Button size="sm" onClick={() => inject("ROAD", selected, "RESTORE")}>
                  RESTORE
                </Button>
              </div>
            </div>
          )}
        </section>

        {/* Right: injections + log */}
        <aside className="flex min-h-0 flex-col border-l border-border bg-surface">
          {selected ? (
            <div className="border-b border-border px-3 py-2">
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
                Propagation — {selected}
              </h3>
              {!propagation ? (
                <p className="text-[10px] text-muted">Chargement…</p>
              ) : (
                <ul className="space-y-1 text-[10px]">
                  {Object.entries(propagation.checks).map(([key, ok]) => (
                    <li key={key} className="flex items-center gap-1.5">
                      {ok ? (
                        <Check className="size-3 text-emerald-600" />
                      ) : (
                        <X className="size-3 text-red-500" />
                      )}
                      <span className="text-foreground/90">{key.replace(/_/g, " ")}</span>
                    </li>
                  ))}
                </ul>
              )}
              {propagation?.command_status === "FAILED" ? (
                <p className="mt-2 text-[10px] text-danger">
                  Échec {propagation.failure_stage}: {propagation.failure_reason}
                </p>
              ) : null}
            </div>
          ) : null}
          <div className="border-b border-border px-3 py-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted">Tests actifs</h3>
          </div>
          <div className="max-h-[40%] overflow-y-auto border-b border-border px-2 py-2">
            {injections.length === 0 ? (
              <p className="px-1 text-[11px] text-muted">Aucune injection active</p>
            ) : (
              injections.map((inj) => (
                <div key={String(inj.injection_id)} className="mb-2 rounded-md border border-border/70 px-2 py-1.5 text-[11px]">
                  <div className="font-semibold text-foreground">
                    {String(inj.target_id)} · {String(inj.action)}
                  </div>
                  <div className="text-muted">
                    {inj.expires_at ? `Expire ${formatSimClock(String(inj.expires_at))}` : "Jusqu'à restauration"}
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="mt-1 h-6 px-2 text-[10px]"
                    onClick={() =>
                      run(async () => {
                        if (inj.command_id) await simApi.cancelInjection(String(inj.command_id))
                        else
                          await simApi.inject({
                            target_type: String(inj.target_type),
                            target_id: String(inj.target_id),
                            action: "RESTORE",
                          })
                      })
                    }
                  >
                    Annuler / Restore
                  </Button>
                </div>
              ))
            )}
          </div>

          <div className="border-b border-border px-3 py-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted">Journal live</h3>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2 font-mono text-[10px]">
            {log.map((row, i) => (
              <div key={`${row.ts}-${i}`} className="mb-1.5 border-b border-border/40 pb-1">
                <span className="text-muted">{formatSimClock(row.ts)}</span>{" "}
                <span
                  className={cn(
                    "rounded px-1 font-sans text-[9px] font-semibold uppercase",
                    row.kind === "TEST" ? "bg-orange-100 text-orange-800" : "bg-slate-100 text-slate-700"
                  )}
                >
                  {row.kind}
                </span>
                <div className="text-foreground/90">{row.message}</div>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  )
}

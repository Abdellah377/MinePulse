import { useEffect, useMemo, useState } from "react"
import { HelpCircle } from "lucide-react"

import { useOpsStore, useSiteScopedEquipment, useSiteScopedZones } from "@/lib/store/useOpsStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import { useApiMode } from "@/lib/api/client"
import { MERAH_SHIFT_SCENARIO } from "@/lib/mock/scenario"
import { formatClock } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { PerformanceMetric } from "@/lib/workspace/types"
import { performanceMetricLabel } from "@/lib/workspace/titles"
import {
  PERFORMANCE_METRICS,
  buildPerformanceAnalysis,
} from "@/lib/performance/metrics"
import type { WorkspacePanelProps } from "@/components/workspace/WorkspaceHost"
import { PerformanceChart } from "@/components/performance/PerformanceChart"
import { PerformanceTable } from "@/components/performance/PerformanceTable"
import { ExportExcelButton } from "@/components/performance/ExportExcelButton"
import { PeriodFilters, formatPeriodLabel } from "@/components/shared/PeriodFilters"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { FileText, FileSpreadsheet, ClipboardList } from "lucide-react"

export default function Performance({ tab }: Partial<WorkspacePanelProps> = {}) {
  const [mode, setMode] = useState<"analyse" | "documents">("analyse")

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Tabs
        value={mode}
        onValueChange={(v) => setMode(v as typeof mode)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-2">
          <p className="text-[12px] font-semibold text-foreground">Performance</p>
          <TabsList className="h-8 rounded-lg bg-surface-2 p-0.5">
            <TabsTrigger value="analyse" className="h-7 rounded-md px-3 text-[12px]">
              Analyse
            </TabsTrigger>
            <TabsTrigger value="documents" className="h-7 rounded-md px-3 text-[12px]">
              Documents
            </TabsTrigger>
          </TabsList>
        </div>
        <TabsContent
          value="analyse"
          className="mt-0 min-h-0 flex-1 overflow-hidden data-[state=inactive]:hidden"
        >
          <PerformanceAnalyse tab={tab} />
        </TabsContent>
        <TabsContent
          value="documents"
          className="mt-0 min-h-0 flex-1 overflow-y-auto p-4 data-[state=inactive]:hidden"
        >
          <DocumentsLite />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function PerformanceAnalyse({ tab }: { tab?: WorkspacePanelProps["tab"] }) {
  const equipment = useSiteScopedEquipment()
  const zones = useSiteScopedZones()
  const sites = useOpsStore((s) => s.sites)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const shifts = useOpsStore((s) => s.shifts)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)
  const periodFrom = useOpsStore((s) => s.periodFrom)
  const periodTo = useOpsStore((s) => s.periodTo)
  const production = useOpsStore((s) => s.productionByShift)
  const downtimeReasons = useOpsStore((s) => s.downtimeReasons)
  const lastSuccessfulSyncAt = useOpsStore((s) => s.lastSuccessfulSyncAt)
  const apiPollError = useOpsStore((s) => s.apiPollError)
  const setTabTitle = useWorkspaceStore((s) => s.setTabTitle)
  const patchTabContext = useWorkspaceStore((s) => s.patchTabContext)
  const setTabState = useWorkspaceStore((s) => s.setTabState)

  const siteName =
    sites.find((s) => s.id === selectedSiteId)?.name ?? (useApiMode ? selectedSiteId : MERAH_SHIFT_SCENARIO.siteName)
  const shiftLabel =
    shifts.find((s) => s.id === selectedShiftId)?.name ?? (useApiMode ? selectedShiftId : MERAH_SHIFT_SCENARIO.shiftLabel)
  const selectedShift = shifts.find((s) => s.id === selectedShiftId)
  const periodLabel = useApiMode ? (selectedShift?.windowStart && selectedShift.windowEnd ? `${new Date(selectedShift.windowStart).toLocaleString("fr-FR")} – ${new Date(selectedShift.windowEnd).toLocaleString("fr-FR")}` : "Fenêtre indisponible") : formatPeriodLabel(periodFrom, periodTo)
  const freshnessValue = useApiMode
    ? apiPollError || lastSuccessfulSyncAt == null
      ? "—"
      : formatClock(new Date(lastSuccessfulSyncAt))
    : formatClock(new Date())

  const initialMetric = (tab?.context.metric as PerformanceMetric | undefined) ?? "production"
  const [metric, setMetric] = useState<PerformanceMetric>(initialMetric)
  const [fuelMode, setFuelMode] = useState<"lph" | "lpt" | "idle">("lph")
  const [visibleCols, setVisibleCols] = useState<string[] | undefined>()
  const [noCauseOnly, setNoCauseOnly] = useState(false)

  useEffect(() => {
    if (tab?.context.metric && tab.context.metric !== metric) {
      setMetric(tab.context.metric as PerformanceMetric)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync from tab only when tab changes
  }, [tab?.id, tab?.context.metric])

  useEffect(() => {
    if (!tab?.id) return
    const title = `Performance — ${performanceMetricLabel(metric)}`
    setTabTitle(tab.id, title)
    patchTabContext(tab.id, { metric })
    setTabState(tab.id, { metric, fuelMode, noCauseOnly })
  }, [tab?.id, metric, fuelMode, noCauseOnly, setTabTitle, patchTabContext, setTabState])

  const analysis = useMemo(() => {
    const base = buildPerformanceAnalysis({
      metric,
      equipment,
      zones,
      productionHourly: production.hourly,
      productionShiftly: production.shiftly,
      downtimeReasons,
      siteId: selectedSiteId,
      fuelMode,
    })
    if (metric === "downtime" && noCauseOnly) {
      return {
        ...base,
        rows: base.rows.filter((r) => !r.cause || r.cause === "—"),
      }
    }
    return base
  }, [metric, equipment, zones, production.hourly, production.shiftly, downtimeReasons, selectedSiteId, fuelMode, noCauseOnly])

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      <aside className="flex w-[200px] shrink-0 flex-col overflow-hidden border-r border-border bg-surface">
        <div className="flex h-10 shrink-0 items-center px-3 text-[11px] font-semibold uppercase tracking-wide text-foreground/80">
          Paramètres
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
          <PeriodFilters />
        </div>
      </aside>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain p-4">
      {/* Context bar */}
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">
              Visualiser
            </span>
            <Select value={metric} onValueChange={(v) => setMetric(v as PerformanceMetric)}>
              <SelectTrigger className="h-9 w-[240px] text-[13px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PERFORMANCE_METRICS.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <MetaChip label="Site" value={siteName} />
          <MetaChip label="Poste" value={shiftLabel} />
          <MetaChip label="Période" value={periodLabel} />
          <MetaChip label="Fraîcheur" value={freshnessValue} />
        </div>
        <ExportExcelButton
          analysis={analysis}
          visibleColumnIds={visibleCols}
          siteName={siteName}
          shiftLabel={shiftLabel}
        />
      </div>

      {/* KPIs */}
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {analysis.kpis.map((k) => (
          <div
            key={k.id}
            className="rounded-md border border-border bg-surface px-3 py-2 shadow-soft-sm"
          >
            <div className="flex items-center gap-1 text-[10px] font-semibold uppercase text-muted-2">
              {k.label}
              {k.hint && (
                <span title={k.hint} className="text-muted-2">
                  <HelpCircle className="size-3" />
                </span>
              )}
            </div>
            <p
              className={cn(
                "mt-0.5 font-mono text-[16px] font-semibold tabular-nums",
                k.tone === "bad" && "text-danger",
                k.tone === "warn" && "text-warning",
                k.tone === "good" && "text-success",
                !k.tone && "text-foreground"
              )}
            >
              {k.value}
            </p>
          </div>
        ))}
      </div>

      {metric === "fuel" && (
        <div className="mb-3 flex w-fit gap-1 rounded-lg bg-surface-2 p-0.5">
          {(
            [
              ["lph", "l/h"],
              ["lpt", "L/t"],
              ["idle", "Idle L"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setFuelMode(id)}
              className={cn(
                "h-7 rounded-md px-2.5 text-[11px] font-medium",
                fuelMode === id ? "bg-surface text-foreground shadow-sm" : "text-muted"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {metric === "downtime" && !useApiMode && (
        <label className="mb-3 flex w-fit items-center gap-1.5 text-[11px] text-muted">
          <input
            type="checkbox"
            checked={noCauseOnly}
            onChange={() => setNoCauseOnly((v) => !v)}
            className="size-3 accent-accent"
          />
          Sans cause uniquement
        </label>
      )}

      <div className="mb-3 grid grid-cols-1 gap-3 xl:grid-cols-12">
        <section className="overflow-hidden rounded-md border border-border bg-surface p-3 shadow-soft xl:col-span-7">
          <h3 className="mb-2 text-[12px] font-semibold text-foreground">
            {analysis.title} — graphique
          </h3>
          <PerformanceChart analysis={analysis} />
        </section>
        <section className="rounded-md border border-border bg-surface p-3 shadow-soft xl:col-span-5">
          <h3 className="mb-2 text-[12px] font-semibold text-foreground">Interprétation</h3>
          <div className="space-y-2 text-[11px]">
            <Block title="Faits" items={analysis.interpretation.facts} />
            <p>
              <span className="font-semibold text-foreground/80">Inférence — </span>
              <span className="text-muted">{analysis.interpretation.inference}</span>
            </p>
            <Block title="Données manquantes" items={analysis.interpretation.missing} />
            <p className="text-muted-2">Confiance : {analysis.interpretation.confidence == null ? "Non évalué" : `${analysis.interpretation.confidence} %`}</p>
          </div>
        </section>
      </div>

      <section className="relative z-0 rounded-md border border-border bg-surface p-3 shadow-soft">
        <PerformanceTable analysis={analysis} onVisibleColumnsChange={setVisibleCols} />
      </section>
      </div>
    </div>
  )
}

function MetaChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[9px] font-semibold uppercase text-muted-2">{label}</span>
      <span className="text-[11px] text-foreground/90">{value}</span>
    </div>
  )
}

function Block({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="font-semibold text-foreground/80">{title}</p>
      <ul className="mt-0.5 list-inside list-disc text-muted">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </div>
  )
}

function DocumentsLite() {
  if (useApiMode) return <p className="text-sm text-muted">Bibliothèque de documents non connectée. Les exports des données affichées restent disponibles dans Analyse.</p>
  const docs = [
    { icon: ClipboardList, title: "Rapport de poste", meta: "Brouillon · ce matin" },
    { icon: FileSpreadsheet, title: "Export production", meta: "Excel · hier" },
    { icon: FileText, title: "Synthèse hebdo", meta: "PDF · lundi" },
  ]
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {docs.map((d) => (
        <div
          key={d.title}
          className="flex items-start gap-3 rounded-md border border-border bg-surface p-3"
        >
          <d.icon className="mt-0.5 size-4 text-muted-2" />
          <div>
            <p className="text-[12px] font-medium">{d.title}</p>
            <p className="text-[10px] text-muted-2">{d.meta}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

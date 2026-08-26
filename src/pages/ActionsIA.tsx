import { useEffect, useMemo, useState } from "react"
import { Sparkles, Flag, Bookmark, AlertTriangle } from "lucide-react"

import {
  useOpsStore,
  useSiteScopedEquipment,
  useSiteScopedZones,
} from "@/lib/store/useOpsStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import {
  DISPATCH_KIND_LABEL,
  dispatchOptimizationBundle,
  projectSnapshot,
} from "@/lib/ai/dispatch"
import { getIntelligenceItem } from "@/lib/ai/alertIntelligence"
import { useApiMode } from "@/lib/api/client"
import { MERAH_SHIFT_SCENARIO } from "@/lib/mock/scenario"
import { cn } from "@/lib/utils"
import type { WorkspacePanelProps } from "@/components/workspace/WorkspaceHost"
import { ScenarioComparison } from "@/components/shared/ScenarioComparison"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { InvestigationActions } from "@/components/ai/InvestigationActions"
import { Chip } from "@/components/ai/InvestigationLayout"

type ActionStatus = "pending" | "prepared" | "marked" | "dismissed"

export default function ActionsIA(props: Partial<WorkspacePanelProps> = {}) {
  return useApiMode ? <InvestigationActions {...props} /> : <DemoActionsIA {...props} />
}

/** Dispatch scenarios are demonstrations, not backend recommendations. */
function DemoActionsIA({ tab }: Partial<WorkspacePanelProps> = {}) {
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const productionByShift = useOpsStore((s) => s.productionByShift)
  const idleThresholdMin = useOpsStore((s) => s.idleAlertThresholdMin)
  const alerts = useOpsStore((s) => s.alerts)
  const equipment = useSiteScopedEquipment()
  const zones = useSiteScopedZones()
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const setTabDirty = useWorkspaceStore((s) => s.setTabDirty)
  const setTabTitle = useWorkspaceStore((s) => s.setTabTitle)

  const [statusById, setStatusById] = useState<Record<string, ActionStatus>>({})
  const [simulatingId, setSimulatingId] = useState<string | null>(null)

  const ctx = tab?.context ?? {}
  const issueId = (ctx.alertId as string | undefined) ?? (ctx.predictionId as string | undefined)

  const issue = useMemo(() => {
    if (!issueId) return null
    return getIntelligenceItem(issueId, alerts, equipment, zones)
  }, [issueId, alerts, equipment, zones])

  const bundle = useMemo(() => {
    try {
      return dispatchOptimizationBundle(
        selectedSiteId,
        equipment,
        zones,
        productionByShift,
        idleThresholdMin
      )
    } catch {
      return null
    }
  }, [selectedSiteId, equipment, zones, productionByShift, idleThresholdMin])

  const recommendations = useMemo(() => {
    if (!bundle) return []
    const zoneName = (ctx.zoneName as string | undefined) ?? issue?.zoneName ?? undefined
    const eqCode = (ctx.equipmentCode as string | undefined) ?? issue?.equipmentCode ?? undefined
    let recs = bundle.recommendations
    if (zoneName || eqCode) {
      const filtered = recs.filter((r) => {
        const zoneHit =
          !zoneName ||
          r.why.includes(zoneName) ||
          r.title.includes(zoneName) ||
          r.action.includes(zoneName) ||
          zones.some((z) => z.name === zoneName && r.zoneIds.includes(z.id))
        const eqHit =
          !eqCode ||
          (r.evidence ?? []).some((e) => e.includes(eqCode)) ||
          equipment.some((e) => e.code === eqCode && r.equipmentIds.includes(e.id))
        return zoneHit || eqHit
      })
      if (filtered.length > 0) recs = filtered
    }
    return recs
  }, [bundle, ctx.zoneName, ctx.equipmentCode, issue, zones, equipment])

  const simulatingRec = recommendations.find((r) => r.id === simulatingId) ?? null
  const projected = useMemo(() => {
    if (!bundle || !simulatingRec) return null
    try {
      return projectSnapshot(bundle.baseline, [simulatingRec])
    } catch {
      return null
    }
  }, [bundle, simulatingRec])

  const preparedCount = Object.values(statusById).filter(
    (s) => s === "prepared" || s === "marked"
  ).length

  useEffect(() => {
    if (!tab?.id) return
    const focus =
      (typeof ctx.zoneName === "string" ? ctx.zoneName : undefined) ??
      (typeof ctx.equipmentCode === "string" ? ctx.equipmentCode : undefined) ??
      issue?.zoneName ??
      issue?.equipmentCode ??
      undefined
    if (focus) setTabTitle(tab.id, `Actions IA — ${focus}`)
    setTabDirty(tab.id, preparedCount > 0)
  }, [
    tab?.id,
    typeof ctx.zoneName === "string" ? ctx.zoneName : "",
    typeof ctx.equipmentCode === "string" ? ctx.equipmentCode : "",
    issue?.zoneName,
    issue?.equipmentCode,
    preparedCount,
    setTabTitle,
    setTabDirty,
  ])

  // Guard: home Actions IA without inherited alert/prediction
  if (!issueId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
        <Sparkles className="size-8 text-muted-2" />
        <h2 className="text-[15px] font-semibold text-foreground">Actions IA</h2>
        <p className="max-w-md text-[12px] text-muted">
          Sélectionnez une alerte ou une prédiction dans Alertes IA, puis cliquez sur
          « Générer des solutions IA » pour ouvrir un plan contextualisé.
        </p>
        <Button
          onClick={() => openWorkspace({ type: "alerts", title: "Alertes IA" })}
        >
          Ouvrir Alertes IA
        </Button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="shrink-0 border-b border-border bg-surface px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">
              Actions IA · contexte hérité
            </p>
            <h1 className="mt-0.5 text-[15px] font-semibold text-foreground">
              {issue?.title ?? "Plan d’action"}
            </h1>
            <p className="mt-1 max-w-2xl text-[12px] text-muted">
              {issue?.summary ??
                (useApiMode ? "Sélectionnez une alerte pour contextualiser les actions." : MERAH_SHIFT_SCENARIO.narrative.body)}
            </p>
          </div>
          {issue && (
            <Badge variant="outline" className="shrink-0">
              Confiance {issue.confidence} %
            </Badge>
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Chip>
            Pourquoi :{" "}
            {issue?.probableCause ??
              (useApiMode ? "—" : MERAH_SHIFT_SCENARIO.narrative.action)}
          </Chip>
          {(issue?.signals ?? (useApiMode ? [] : MERAH_SHIFT_SCENARIO.narrative.evidence.slice(0, 3))).map((s) => (
            <Chip key={s}>{s}</Chip>
          ))}
        </div>
      </header>

      <div className="grid min-h-0 flex-1 gap-3 overflow-hidden p-4 lg:grid-cols-12">
        <div className="flex min-h-0 flex-col gap-2 overflow-y-auto lg:col-span-7">
          <h2 className="text-[12px] font-semibold text-foreground">
            Recommandations ({recommendations.length})
          </h2>
          {recommendations.map((rec) => {
            const status = statusById[rec.id] ?? "pending"
            const simulating = simulatingId === rec.id
            if (status === "dismissed") return null
            return (
              <article
                key={rec.id}
                className={cn(
                  "rounded-md border px-3.5 py-3",
                  simulating
                    ? "border-accent/40 bg-accent-soft/40"
                    : status === "prepared" || status === "marked"
                      ? "border-success/30 bg-success/5"
                      : "border-border bg-surface"
                )}
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline" className="text-[10px]">
                    {DISPATCH_KIND_LABEL[rec.kind]}
                  </Badge>
                  {(status === "prepared" || status === "marked") && (
                    <Badge className="border-transparent bg-success/15 text-success text-[10px]">
                      {status === "marked" ? "Marqué" : "Préparé"}
                    </Badge>
                  )}
                  <span className="ml-auto text-[10px] text-muted-2">
                    Conf. {rec.confidence} %
                  </span>
                </div>
                <h3 className="mt-1.5 text-[13px] font-semibold text-foreground">{rec.title}</h3>
                <p className="mt-1 text-[11px] text-muted">{rec.why}</p>
                <p className="mt-1 text-[11px] text-foreground/85">
                  <span className="font-medium">Action — </span>
                  {rec.action}
                </p>
                <div className="mt-2 flex flex-wrap gap-3 text-[11px] tabular-nums">
                  <span className="text-success">+{rec.impactTonsPerHour} t/h</span>
                  <span className="text-accent">−{rec.impactWaitMin} min attente</span>
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  <Button
                    size="sm"
                    variant={simulating ? "default" : "outline"}
                    onClick={() => setSimulatingId((c) => (c === rec.id ? null : rec.id))}
                  >
                    Simuler
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setStatusById((p) => ({ ...p, [rec.id]: "prepared" }))}
                  >
                    <Flag className="size-3.5" />
                    Préparer
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setStatusById((p) => ({ ...p, [rec.id]: "marked" }))}
                  >
                    <Bookmark className="size-3.5" />
                    Marquer
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setStatusById((p) => ({ ...p, [rec.id]: "dismissed" }))
                      if (simulatingId === rec.id) setSimulatingId(null)
                    }}
                  >
                    Ignorer
                  </Button>
                </div>
              </article>
            )
          })}
          {recommendations.every((r) => statusById[r.id] === "dismissed") && (
            <p className="py-8 text-center text-xs text-muted">Toutes les options ont été ignorées.</p>
          )}
        </div>

        <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto lg:col-span-5">
          <div className="rounded-md border border-border bg-surface p-3">
            <h3 className="text-[12px] font-semibold text-foreground">Simulation / comparaison</h3>
            {simulatingRec && projected && bundle ? (
              <div className="mt-2">
                <ScenarioComparison
                  baseline={bundle.baseline}
                  projected={projected}
                  title={simulatingRec.title}
                  subtitle="Avant / après estimé"
                />
              </div>
            ) : (
              <p className="mt-2 flex items-start gap-2 text-[11px] text-muted">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-muted-2" />
                Cliquez Sur « Simuler » sur une carte pour comparer l’avant / après estimé.
              </p>
            )}
          </div>
          <div className="rounded-md border border-border bg-surface p-3 text-[11px] text-muted">
            <p className="font-semibold text-foreground/80">Rappel</p>
            <p className="mt-1">
              Préparer · Marquer · Ignorer — aucune application automatique au FMS. Les actions
              préparées restent sous contrôle du chef de poste.
            </p>
            {preparedCount > 0 && (
              <p className="mt-2 text-success">{preparedCount} action(s) préparée(s) / marquée(s).</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

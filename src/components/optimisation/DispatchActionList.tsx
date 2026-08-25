import { Film as FilmIcon, Map as MapIcon, Flag, Bookmark } from "lucide-react"

import { cn } from "@/lib/utils"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import {
  DISPATCH_KIND_LABEL,
  type DispatchRecommendation,
} from "@/lib/ai/dispatch"
import { Button } from "@/components/ui/button"

type ActionStatus = "pending" | "prepared" | "marked" | "dismissed" | "applied"

export function DispatchActionList({
  recommendations,
  statusById,
  simulatingId,
  onPrepare,
  onMark,
  onSimulate,
  onDismiss,
  /** @deprecated use onPrepare — kept for soft compatibility */
  onApply,
}: {
  recommendations: DispatchRecommendation[]
  statusById: Record<string, ActionStatus>
  simulatingId: string | null
  onPrepare?: (id: string) => void
  onMark?: (id: string) => void
  onSimulate: (id: string) => void
  onDismiss: (id: string) => void
  onApply?: (id: string) => void
}) {
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const visible = recommendations.filter((r) => statusById[r.id] !== "dismissed")
  const prepare = onPrepare ?? onApply

  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-border/80 bg-surface shadow-soft">
      <div className="flex shrink-0 items-center justify-between gap-3 px-4 py-3">
        <div>
          <h2 className="text-[13px] font-semibold text-foreground">Options recommandées</h2>
          <p className="text-[11px] text-muted">Préparer · Marquer · Ignorer — pas d&apos;application auto</p>
        </div>
        <span className="rounded-md bg-surface-2 px-2 py-0.5 text-[11px] tabular-nums text-muted-2">
          {visible.length}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <ul className="flex flex-col gap-2">
          {visible.map((rec, index) => {
            const status = statusById[rec.id] ?? "pending"
            const simulating = simulatingId === rec.id
            return (
              <li
                key={rec.id}
                className={cn(
                  "rounded-xl border px-3.5 py-3 transition-colors",
                  simulating
                    ? "border-accent/35 bg-accent-soft/50"
                    : status === "prepared" || status === "marked" || status === "applied"
                      ? "border-success/25 bg-success/5"
                      : "border-border bg-surface-2/40"
                )}
              >
                <div className="flex flex-wrap items-start gap-2">
                  <span className="rounded-md bg-surface px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-muted-2">
                    #{index + 1}
                  </span>
                  <span className="rounded-md bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                    {DISPATCH_KIND_LABEL[rec.kind]}
                  </span>
                  {(status === "prepared" || status === "applied") && (
                    <span className="rounded-md bg-success/15 px-1.5 py-0.5 text-[10px] font-semibold text-success">
                      Préparé
                    </span>
                  )}
                  {status === "marked" && (
                    <span className="rounded-md bg-warning/15 px-1.5 py-0.5 text-[10px] font-semibold text-warning">
                      Marqué
                    </span>
                  )}
                  <span className="ml-auto text-[10px] tabular-nums text-muted-2">
                    Confiance {rec.confidence} %
                  </span>
                </div>

                <h3 className="mt-2 text-[13px] font-semibold text-foreground">{rec.title}</h3>
                <p className="mt-1 text-[12px] leading-relaxed text-muted">{rec.why}</p>

                <ul className="mt-2 flex flex-col gap-0.5 text-[11px] text-muted">
                  {rec.evidence.map((e) => (
                    <li key={e} className="flex gap-1.5">
                      <span className="text-accent">·</span>
                      <span>{e}</span>
                    </li>
                  ))}
                </ul>

                <div className="mt-2.5 flex flex-wrap items-center gap-3 text-[11px]">
                  <span className="font-semibold tabular-nums text-success">
                    +{rec.impactTonsPerHour} t/h
                  </span>
                  <span className="font-semibold tabular-nums text-foreground/80">
                    −{rec.impactWaitMin} min attente
                  </span>
                </div>

                <p className="mt-2 rounded-lg bg-surface px-2.5 py-2 text-[11px]">
                  <span className="font-semibold text-accent">Faire · </span>
                  <span className="text-foreground/85">{rec.action}</span>
                </p>

                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  {prepare && (
                    <Button
                      size="sm"
                      disabled={status === "prepared" || status === "applied"}
                      onClick={() => prepare(rec.id)}
                    >
                      <Flag className="size-3.5" />
                      Préparer
                    </Button>
                  )}
                  {onMark && (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={status === "marked"}
                      onClick={() => onMark(rec.id)}
                    >
                      <Bookmark className="size-3.5" />
                      Marquer
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant={simulating ? "secondary" : "outline"}
                    onClick={() => onSimulate(rec.id)}
                  >
                    {simulating ? "Simulation active" : "Simuler"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onDismiss(rec.id)}
                  >
                    Ignorer
                  </Button>
                  <div className="ml-auto flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-[11px]"
                      onClick={() => openWorkspace({ type: "timeline" })}
                      title="Ouvrir Film"
                    >
                      <FilmIcon className="size-3.5" />
                      Film
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-[11px]"
                      onClick={() => openWorkspace({ type: "map" })}
                      title="Ouvrir Carte"
                    >
                      <MapIcon className="size-3.5" />
                      Carte
                    </Button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
        {visible.length === 0 && (
          <p className="py-10 text-center text-xs text-muted">
            Toutes les options ont été ignorées.
          </p>
        )}
      </div>
    </section>
  )
}

import { cn } from "@/lib/utils"
import type { DispatchObjective } from "@/lib/ai/dispatch"

export function ImpactSummary({
  objective,
  appliedGainTons,
}: {
  objective: DispatchObjective
  appliedGainTons: number
}) {
  const projected =
    objective.attainmentPct == null
      ? null
      : Math.min(112, objective.attainmentPct + appliedGainTons * 0.55)

  return (
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Metric
        label="Atteinte poste"
        value={objective.attainmentPct != null ? `${objective.attainmentPct.toFixed(0)} %` : "—"}
        hint={
          objective.tonnage != null && objective.target != null
            ? `${objective.tonnage} / ${objective.target} t`
            : objective.tonnage != null
              ? `${objective.tonnage} t · objectif —`
              : "—"
        }
        tone={
          objective.attainmentPct == null
            ? "default"
            : objective.attainmentPct >= 95
              ? "good"
              : objective.attainmentPct >= 85
                ? "warn"
                : "bad"
        }
      />
      <Metric
        label="Attente moyenne"
        value={`${objective.avgWaitMin.toFixed(0)} min`}
        hint="Camions — poste en cours"
      />
      <Metric
        label="Tonnage perdu (estim.)"
        value={`${objective.lostTonsFromWait} t`}
        hint="Lié aux attentes"
        tone="bad"
      />
      <Metric
        label="Gain si plan appliqué"
        value={`+${(objective.predictedGainTonsPerHour + appliedGainTons * 0.3).toFixed(0)} t/h`}
        hint={`Atteinte projetée ≈ ${projected != null ? projected.toFixed(0) : "—"} %`}
        tone="good"
      />
    </section>
  )
}

function Metric({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string
  value: string
  hint?: string
  tone?: "default" | "good" | "warn" | "bad"
}) {
  return (
    <div className="rounded-xl border border-border/80 bg-surface px-4 py-3 shadow-soft-sm">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">{label}</p>
      <p
        className={cn(
          "mt-1.5 text-xl font-semibold tabular-nums tracking-tight",
          tone === "good" && "text-success",
          tone === "warn" && "text-warning",
          tone === "bad" && "text-danger",
          tone === "default" && "text-foreground"
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-[11px] text-muted">{hint}</p>}
    </div>
  )
}

import { cn } from "@/lib/utils"
import type { DispatchSimSnapshot } from "@/lib/ai/dispatch"

export function ScenarioComparison({
  baseline,
  projected,
  title = "Comparaison de scénarios",
  subtitle,
  className,
}: {
  baseline: DispatchSimSnapshot
  projected: DispatchSimSnapshot | null
  title?: string
  subtitle?: string | null
  className?: string
}) {
  return (
    <section
      className={cn(
        "flex flex-col overflow-hidden rounded-xl border border-border/80 bg-surface shadow-soft",
        className
      )}
    >
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-[13px] font-semibold text-foreground">{title}</h3>
        {subtitle && <p className="mt-0.5 text-[11px] text-muted">{subtitle}</p>}
        {!projected && (
          <p className="mt-1 text-[11px] text-muted-2">Sélectionnez une option pour comparer.</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-px bg-border">
        <Col
          label="Actuel"
          wait={baseline.avgWaitMin}
          cycle={baseline.avgCycleMin}
          attainment={baseline.attainmentPct}
        />
        <Col
          label="Simulé"
          wait={projected?.avgWaitMin ?? null}
          cycle={projected?.avgCycleMin ?? null}
          attainment={projected?.attainmentPct ?? null}
          highlight
        />
      </div>

      {projected && (
        <div className="flex flex-col gap-1.5 px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">
            Pression zones (simulé)
          </p>
          {projected.zonePressures.slice(0, 3).map((z) => (
            <div key={z.zoneId} className="flex items-center gap-2 text-[11px]">
              <span className="min-w-0 flex-1 truncate text-foreground/85">{z.name}</span>
              <span className="tabular-nums text-muted">
                {z.count}/{z.capacity}
              </span>
              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-2">
                <div
                  className={cn(
                    "h-full rounded-full",
                    z.ratio >= 1 ? "bg-danger" : z.ratio >= 0.7 ? "bg-warning" : "bg-accent"
                  )}
                  style={{ width: `${Math.min(100, z.ratio * 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function Col({
  label,
  wait,
  cycle,
  attainment,
  highlight,
}: {
  label: string
  wait: number | null
  cycle: number | null
  attainment: number | null
  highlight?: boolean
}) {
  return (
    <div className={cn("flex flex-col gap-2 bg-surface px-4 py-3", highlight && "bg-accent-soft/40")}>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">{label}</p>
      <Metric label="Attente moy." value={wait != null ? `${wait.toFixed(0)} min` : "—"} />
      <Metric label="Cycle moy." value={cycle != null ? `${cycle.toFixed(0)} min` : "—"} />
      <Metric
        label="Atteinte"
        value={attainment != null ? `${attainment.toFixed(0)} %` : "—"}
        emphasize={highlight && attainment != null}
      />
    </div>
  )
}

function Metric({
  label,
  value,
  emphasize,
}: {
  label: string
  value: string
  emphasize?: boolean
}) {
  return (
    <div>
      <p className="text-[10px] text-muted-2">{label}</p>
      <p
        className={cn(
          "font-mono text-[14px] font-semibold tabular-nums",
          emphasize ? "text-accent" : "text-foreground"
        )}
      >
        {value}
      </p>
    </div>
  )
}

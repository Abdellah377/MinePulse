import { cn } from "@/lib/utils"
import type { DispatchSimSnapshot } from "@/lib/ai/dispatch"

export function BeforeAfterSim({
  baseline,
  projected,
  activeTitle,
}: {
  baseline: DispatchSimSnapshot
  projected: DispatchSimSnapshot | null
  activeTitle: string | null
}) {
  if (!projected || !activeTitle) {
    return (
      <section className="flex h-full min-h-[200px] flex-col justify-center rounded-xl border border-dashed border-border bg-surface/60 px-4 py-6 text-center shadow-soft-sm">
        <p className="text-[13px] font-semibold text-foreground">Simulation avant / après</p>
        <p className="mt-1 text-[12px] text-muted">
          Sélectionnez <span className="font-medium text-foreground/80">Simuler</span> sur une action
          pour comparer le poste actuel au scénario projeté.
        </p>
      </section>
    )
  }

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-xl border border-border/80 bg-surface shadow-soft">
      <div className="px-4 py-3">
        <h2 className="text-[13px] font-semibold text-foreground">Simulation avant / après</h2>
        <p className="mt-0.5 truncate text-[11px] text-muted">{activeTitle}</p>
      </div>

      <div className="grid grid-cols-2 gap-2 px-3 pb-2">
        <CompareCard label="Actuel" snap={baseline} />
        <CompareCard label="Projeté" snap={projected} highlight />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          Pression zones
        </p>
        <div className="flex flex-col gap-2">
          {baseline.zonePressures.map((z) => {
            const proj = projected.zonePressures.find((p) => p.zoneId === z.zoneId) ?? z
            return (
              <div key={z.zoneId} className="rounded-lg bg-surface-2/60 px-2.5 py-2">
                <div className="mb-1.5 flex items-center justify-between text-[11px]">
                  <span className="font-medium text-foreground/90">{z.name}</span>
                  <span className="tabular-nums text-muted">
                    {(z.ratio * 100).toFixed(0)}% →{" "}
                    <span className="font-medium text-accent">{(proj.ratio * 100).toFixed(0)}%</span>
                  </span>
                </div>
                <div className="flex gap-1">
                  <Bar ratio={z.ratio} className="bg-muted-2/50" />
                  <Bar ratio={proj.ratio} className="bg-accent" />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function CompareCard({
  label,
  snap,
  highlight,
}: {
  label: string
  snap: DispatchSimSnapshot
  highlight?: boolean
}) {
  return (
    <div
      className={cn(
        "rounded-lg border px-2.5 py-2",
        highlight ? "border-accent/25 bg-accent-soft/40" : "border-border bg-surface-2/50"
      )}
    >
      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-2">{label}</p>
      <dl className="mt-1.5 space-y-1 text-[11px]">
        <Row k="Atteinte" v={snap.attainmentPct != null ? `${snap.attainmentPct.toFixed(0)} %` : "—"} />
        <Row k="Attente moy." v={`${snap.avgWaitMin.toFixed(0)} min`} />
        <Row k="Cycle moy." v={`${snap.avgCycleMin.toFixed(0)} min`} />
      </dl>
    </div>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-muted">{k}</dt>
      <dd className="font-medium tabular-nums text-foreground">{v}</dd>
    </div>
  )
}

function Bar({ ratio, className }: { ratio: number; className: string }) {
  return (
    <div className="h-1.5 flex-1 overflow-hidden rounded-sm bg-surface-3">
      <div
        className={cn("h-full rounded-sm", className)}
        style={{ width: `${Math.min(100, ratio * 100)}%` }}
      />
    </div>
  )
}

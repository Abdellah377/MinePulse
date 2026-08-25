import { cn } from "@/lib/utils"
import { useApiMode } from "@/lib/api/client"
import { MERAH_SHIFT_SCENARIO, type ShiftScenario } from "@/lib/mock/scenario"
import { getShiftAttainment } from "@/lib/mock/scenarioMetrics"
import { formatNumber } from "@/lib/format"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"

/**
 * Compact shift briefing — headline + 2–3 facts + production strip.
 * AI explanations belong in the exception inspector, not here.
 */
export function OperationalBrief({
  scenario,
  className,
}: {
  scenario?: ShiftScenario
  className?: string
}) {
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  if (useApiMode) return null
  const s = scenario ?? MERAH_SHIFT_SCENARIO
  const att = getShiftAttainment(s)
  const facts = s.narrative.evidence.slice(0, 3)

  return (
    <section
      className={cn(
        "grid shrink-0 gap-3 rounded-md border border-border/80 bg-surface px-4 py-3 lg:grid-cols-12",
        className
      )}
    >
      <div className="lg:col-span-8">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          Brief opérationnel · {s.shiftLabel}
        </p>
        <h2 className="mt-1 text-[15px] font-semibold tracking-tight text-foreground">
          {s.narrative.headline}
        </h2>
        <ul className="mt-2 flex flex-col gap-0.5 text-[12px] text-muted">
          {facts.map((e) => (
            <li key={e} className="flex gap-1.5">
              <span className="text-accent">·</span>
              <span>{e}</span>
            </li>
          ))}
        </ul>
        <div className="mt-2.5 flex flex-wrap gap-2">
          <button
            type="button"
            className="text-[11px] font-medium text-accent hover:underline"
            onClick={() => openWorkspace({ type: "map" })}
          >
            Voir les équipements concernés
          </button>
          <button
            type="button"
            className="text-[11px] font-medium text-accent hover:underline"
            onClick={() => openWorkspace({ type: "timeline" })}
          >
            Ouvrir dans le Film
          </button>
          <button
            type="button"
            className="text-[11px] font-medium text-accent hover:underline"
            onClick={() => openWorkspace({ type: "map" })}
          >
            Ouvrir sur la Carte
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 lg:col-span-4">
        <BriefStat label="Réel" value={`${formatNumber(att.actual)} t`} />
        <BriefStat label="Objectif" value={`${formatNumber(att.target)} t`} />
        <BriefStat label="Écart" value={`−${formatNumber(att.gapTons)} t`} tone="bad" />
      </div>
    </section>
  )
}

function BriefStat({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: "bad"
}) {
  return (
    <div className="rounded-md border border-border bg-surface-2/50 px-2.5 py-2">
      <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-2">{label}</p>
      <p
        className={cn(
          "mt-1 text-[14px] font-semibold tabular-nums",
          tone === "bad" ? "text-danger" : "text-foreground"
        )}
      >
        {value}
      </p>
    </div>
  )
}

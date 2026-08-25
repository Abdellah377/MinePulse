import { cn } from "@/lib/utils"

export interface AiInsight {
  title: string
  body: string
  confidence?: number
  evidence?: string[]
  action?: string
  next?: string
}

interface AiSlotProps {
  insight: AiInsight
  /** hero = page-level primary insight; card = panel; banner = footer strip; chip = compact */
  variant?: "hero" | "card" | "banner" | "chip"
  label?: string
  className?: string
}

/**
 * Contextual AI surface — the product's primary decision layer.
 * Never a chatbot. Always labeled as preview until LangGraph is connected.
 */
export function AiSlot({ insight, variant = "card", label = "Pourquoi", className }: AiSlotProps) {
  if (variant === "chip") {
    return (
      <div
        className={cn(
          "flex max-w-sm items-center gap-2 rounded-xl border border-accent/20 bg-accent-soft/80 px-3 py-1.5 text-[11px]",
          className
        )}
        title="Aperçu IA — non connecté"
      >
        <span className="rounded-md bg-accent/15 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-accent">
          IA
        </span>
        <span className="truncate font-medium text-foreground/85">{insight.title}</span>
      </div>
    )
  }

  if (variant === "banner") {
    return (
      <div
        className={cn(
          "flex items-start gap-3 rounded-xl border border-accent/15 bg-accent-soft/50 px-4 py-3 shadow-soft-sm",
          className
        )}
      >
        <span className="mt-0.5 shrink-0 rounded-md bg-accent px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">
          IA
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[12px] font-semibold text-foreground">{insight.title}</p>
          <p className="mt-0.5 text-[12px] leading-relaxed text-muted">{insight.body}</p>
          {insight.action && (
            <p className="mt-1.5 text-[11px] font-medium text-accent">→ {insight.action}</p>
          )}
        </div>
        <span className="shrink-0 text-[10px] text-muted-2">Aperçu</span>
      </div>
    )
  }

  if (variant === "hero") {
    return (
      <section
        className={cn(
          "rounded-2xl border border-accent/15 bg-surface p-5 shadow-soft",
          className
        )}
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-accent px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
              Intelligence
            </span>
            <span className="text-[11px] font-medium text-muted">Pourquoi · Ensuite · Faire</span>
          </div>
          <span className="rounded-md bg-surface-2 px-2.5 py-0.5 text-[10px] text-muted-2">
            Aperçu — non connecté
          </span>
        </div>

        <h2 className="text-[15px] font-semibold tracking-tight text-foreground">{insight.title}</h2>
        <p className="mt-1.5 max-w-3xl text-[13px] leading-relaxed text-muted">{insight.body}</p>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <InsightColumn
            kicker="Pourquoi"
            body={
              insight.evidence?.length
                ? insight.evidence.slice(0, 2).join(" · ")
                : insight.body
            }
          />
          <InsightColumn
            kicker="Ensuite"
            body={insight.next ?? "Surveiller la zone critique et le prochain cycle d'attente."}
          />
          <InsightColumn
            kicker="Faire"
            body={insight.action ?? "Ouvrir le Film et prioriser les attentes > 15 min."}
            emphasize
          />
        </div>

        {typeof insight.confidence === "number" && (
          <p className="mt-3 text-[11px] text-muted-2">
            Confiance estimée{" "}
            <span className="font-medium tabular-nums text-foreground/70">{insight.confidence}%</span>
          </p>
        )}
      </section>
    )
  }

  /* card — default panel insight */
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-2xl border border-accent/15 bg-accent-soft/40 p-4 shadow-soft-sm",
        className
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-accent px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">
            IA
          </span>
          <span className="text-[11px] font-semibold text-foreground">{label}</span>
        </div>
        <span className="text-[10px] text-muted-2">Aperçu</span>
      </div>
      <p className="text-[12px] font-medium leading-snug text-foreground">{insight.title}</p>
      <p className="text-[12px] leading-relaxed text-muted">{insight.body}</p>
      {typeof insight.confidence === "number" && (
        <div className="text-[11px] text-muted-2">
          Confiance : <span className="font-medium tabular-nums text-foreground/70">{insight.confidence}%</span>
        </div>
      )}
      {insight.evidence && insight.evidence.length > 0 && (
        <ul className="flex flex-col gap-1 text-[11px] text-muted">
          {insight.evidence.map((e, i) => (
            <li key={i} className="flex gap-1.5">
              <span className="text-accent">·</span>
              <span>{e}</span>
            </li>
          ))}
        </ul>
      )}
      {insight.action && (
        <div className="mt-0.5 rounded-xl bg-surface/80 px-3 py-2 text-[11px]">
          <span className="font-semibold text-accent">Faire · </span>
          <span className="text-foreground/85">{insight.action}</span>
        </div>
      )}
    </div>
  )
}

function InsightColumn({
  kicker,
  body,
  emphasize,
}: {
  kicker: string
  body: string
  emphasize?: boolean
}) {
  return (
    <div
      className={cn(
        "rounded-xl border px-3.5 py-3",
        emphasize ? "border-accent/25 bg-accent-soft/60" : "border-border bg-surface-2/60"
      )}
    >
      <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-accent">{kicker}</p>
      <p className="text-[12px] leading-snug text-foreground/85">{body}</p>
    </div>
  )
}

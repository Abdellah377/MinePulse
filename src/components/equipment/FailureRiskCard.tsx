import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { FailureRiskDto, FailureRiskLevel } from "@/lib/api/types/ops"
import {
  FAILURE_RISK_LOADING_COPY,
  FAILURE_RISK_PROTOTYPE_LABEL,
  FAILURE_RISK_PROTOTYPE_WARNING,
  FAILURE_RISK_SIGNALS_UNAVAILABLE,
  FAILURE_RISK_WINDOW_COPY,
  RISK_LEVEL_LABEL,
  failureRiskWhy,
  formatFailureRiskPercent,
} from "@/lib/equipment/failureRisk"
import { AiExplanationBlock, AiExplanationPanel, AiWhyButton } from "@/components/ai/AiExplanation"
import { cn } from "@/lib/utils"

const LEVEL_BADGE: Record<FailureRiskLevel, string> = {
  HIGH: "border-transparent bg-danger/15 text-danger",
  MEDIUM: "border-transparent bg-warning/15 text-warning",
  LOW: "border-transparent bg-muted text-muted",
}

export function FailureRiskCard({
  prediction,
  loading,
  error,
}: {
  prediction?: FailureRiskDto | null
  loading?: boolean
  error?: string | null
}) {
  const [whyOpen, setWhyOpen] = useState(false)

  if (loading) {
    return (
      <div className="flex min-h-[7.5rem] flex-col gap-2 rounded-md border border-border bg-surface-2/40 px-3 py-3" role="status">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          Risque de panne mécanique
        </p>
        <p className="text-xs text-muted">{FAILURE_RISK_LOADING_COPY}</p>
        <div className="mt-1 h-7 w-16 animate-pulse rounded-md bg-surface-3" />
        <div className="h-3 w-full animate-pulse rounded-sm bg-surface-3" />
        <div className="h-3 w-2/3 animate-pulse rounded-sm bg-surface-3" />
      </div>
    )
  }

  if (!prediction) {
    return (
      <div className="flex flex-col gap-2 rounded-md border border-border bg-surface-2/40 px-3 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          Risque de panne mécanique
        </p>
        <p className="text-xs text-muted">Prédiction indisponible.</p>
        {error && <p className="text-[10px] text-muted-2">{error}</p>}
      </div>
    )
  }

  const why = failureRiskWhy(prediction)
  const available =
    prediction.status === "AVAILABLE" && prediction.riskProbability != null
  const horizon = why.horizonMinutes
  const unavailableCopy =
    prediction.status === "INSUFFICIENT_HISTORY"
      ? "Historique insuffisant pour prédire."
      : "Prédiction indisponible."

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border bg-surface-2/40 px-3 py-3">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          Risque de panne mécanique
        </p>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help text-[10px] text-muted-2 underline decoration-dotted underline-offset-2">
              {FAILURE_RISK_PROTOTYPE_LABEL}
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs leading-snug">
            {FAILURE_RISK_PROTOTYPE_WARNING}
          </TooltipContent>
        </Tooltip>
      </div>

      {available ? (
        <>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-2xl font-semibold tabular-nums text-foreground">
              {formatFailureRiskPercent(prediction.riskProbability as number)}
            </span>
            {prediction.riskLevel && (
              <Badge className={cn(LEVEL_BADGE[prediction.riskLevel])}>
                {RISK_LEVEL_LABEL[prediction.riskLevel]}
              </Badge>
            )}
          </div>
          <p className="text-[11px] leading-snug text-muted">{FAILURE_RISK_WINDOW_COPY}</p>
          <p className="text-[10px] text-muted-2">Prochaines {horizon} minutes</p>
          {why.evaluatedAt && (
            <p className="text-[10px] text-muted-2">Télémétrie : {why.evaluatedAt}</p>
          )}
          {why.signalsAvailable && (
            <div>
              <ul className="list-disc pl-4 text-[11px] text-muted">
                {why.signals.slice(0, 3).map((label) => (
                  <li key={label}>{label}</li>
                ))}
              </ul>
              {why.signals.length > 3 && (
                <details className="mt-1">
                  <summary className="cursor-pointer select-none rounded-sm text-[11px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
                    Voir {why.signals.length - 3} autre{why.signals.length - 3 === 1 ? "" : "s"} {why.signals.length - 3 === 1 ? "signal" : "signaux"}
                  </summary>
                  <ul className="mt-1 list-disc pl-4 text-[11px] text-muted">
                    {why.signals.slice(3).map((label) => (
                      <li key={label}>{label}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
          <AiWhyButton expanded={whyOpen} onClick={() => setWhyOpen((open) => !open)} />
          <AiExplanationPanel open={whyOpen}>
            <AiExplanationBlock label="Ce que l’IA a observé">
              Prédiction de modèle — probabilité d’un arrêt mécanique dans les {horizon} prochaines minutes, pas un fait observé.
            </AiExplanationBlock>
            <AiExplanationBlock label="Risque actuel">
              {why.probabilityLabel}
            </AiExplanationBlock>
            <AiExplanationBlock label="Horizon">{horizon} min</AiExplanationBlock>
            <AiExplanationBlock label="Pourquoi le modèle estime-t-il ce risque ?">
              {why.signalsAvailable ? (
                <>
                  <ul className="list-disc pl-4">
                    {why.signals.slice(0, 3).map((label) => (
                      <li key={label}>{label}</li>
                    ))}
                  </ul>
                  {why.signals.length > 3 && (
                    <details className="mt-2">
                      <summary className="cursor-pointer select-none rounded-sm text-[11px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
                        Voir {why.signals.length - 3} autre{why.signals.length - 3 === 1 ? "" : "s"} {why.signals.length - 3 === 1 ? "signal" : "signaux"}
                      </summary>
                      <ul className="mt-1 list-disc pl-4">
                        {why.signals.slice(3).map((label) => (
                          <li key={label}>{label}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </>
              ) : (
                FAILURE_RISK_SIGNALS_UNAVAILABLE
              )}
            </AiExplanationBlock>
            <AiExplanationBlock label="Confiance / incertitude">
              {why.prototype
                ? FAILURE_RISK_PROTOTYPE_WARNING
                : "Prédiction de modèle, pas une panne confirmée."}
              {why.modelVersion ? ` Version ${why.modelVersion}.` : ""}
            </AiExplanationBlock>
          </AiExplanationPanel>
        </>
      ) : (
        <>
          <p className="text-xs text-muted">{unavailableCopy}</p>
          {prediction.detail && (
            <p className="text-[10px] leading-snug text-muted-2">{prediction.detail}</p>
          )}
        </>
      )}
    </div>
  )
}

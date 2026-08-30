import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { FailureRiskDto, FailureRiskLevel } from "@/lib/api/types/ops"
import {
  FAILURE_RISK_PROTOTYPE_LABEL,
  FAILURE_RISK_PROTOTYPE_WARNING,
  FAILURE_RISK_WINDOW_COPY,
  RISK_LEVEL_LABEL,
  formatFailureRiskPercent,
  signalLabel,
} from "@/lib/equipment/failureRisk"
import { cn } from "@/lib/utils"

const LEVEL_BADGE: Record<FailureRiskLevel, string> = {
  HIGH: "border-transparent bg-danger/15 text-danger",
  MEDIUM: "border-transparent bg-warning/15 text-warning",
  LOW: "border-transparent bg-muted text-muted",
}

export function FailureRiskCard({ prediction }: { prediction: FailureRiskDto }) {
  const available =
    prediction.status === "AVAILABLE" && prediction.riskProbability != null
  const horizon = prediction.horizonMinutes || 60

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
        </>
      ) : prediction.status === "INSUFFICIENT_HISTORY" ? (
        <p className="text-xs text-muted">Historique insuffisant pour prédire.</p>
      ) : (
        <p className="text-xs text-muted">Prédiction indisponible.</p>
      )}

      {available && prediction.topPredictiveSignals.length > 0 && (
        <details className="text-[11px] text-muted">
          <summary className="cursor-pointer text-muted-2">Signaux associés</summary>
          <p className="mt-1 text-[10px] text-muted-2">
            Signaux associés au modèle, pas des causes confirmées.
          </p>
          <ul className="mt-1 list-disc pl-4">
            {prediction.topPredictiveSignals.map((name) => (
              <li key={name}>{signalLabel(name)}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

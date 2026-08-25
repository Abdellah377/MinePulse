import type { CycleStage } from "@/lib/mock/types"
import { CycleStepper } from "@/components/parc/CycleStepper"
import { cn } from "@/lib/utils"

/** Thin wrapper around CycleStepper for shared use (inspectors, Performance). */
export function CycleBreakdown({
  stages,
  dureeMoyenneMin,
  title,
  className,
}: {
  stages: CycleStage[]
  dureeMoyenneMin: number
  title?: string
  className?: string
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {title && (
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted">{title}</p>
      )}
      <CycleStepper stages={stages} dureeMoyenneMin={dureeMoyenneMin} />
    </div>
  )
}

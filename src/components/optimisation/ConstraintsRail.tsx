import { Film as FilmIcon, Map as MapIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"

export function ConstraintsRail({
  siteName,
  shiftName,
  idleThresholdMin,
  appliedCount,
  appliedTitles,
}: {
  siteName: string
  shiftName: string
  idleThresholdMin: number
  appliedCount: number
  appliedTitles: string[]
}) {
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)

  return (
    <aside className="flex flex-col gap-3">
      <div className="rounded-xl border border-border/80 bg-surface p-4 shadow-soft-sm">
        <h2 className="text-[12px] font-semibold text-foreground">Contraintes actives</h2>
        <dl className="mt-3 space-y-2 text-[12px]">
          <div className="flex justify-between gap-2">
            <dt className="text-muted">Site</dt>
            <dd className="font-medium text-foreground">{siteName}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-muted">Poste</dt>
            <dd className="font-medium text-foreground">{shiftName}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-muted">Seuil inactivité</dt>
            <dd className="font-medium tabular-nums text-foreground">{idleThresholdMin} min</dd>
          </div>
        </dl>
        <Button
          variant="outline"
          size="sm"
          className="mt-3 w-full"
          onClick={() => openWorkspace({ type: "settings" })}
        >
          Ajuster dans Paramètres
        </Button>
      </div>

      <div className="rounded-xl border border-border/80 bg-surface p-4 shadow-soft-sm">
        <h2 className="text-[12px] font-semibold text-foreground">Aller plus loin</h2>
        <div className="mt-2 flex flex-col gap-1.5">
          <Button
            variant="secondary"
            size="sm"
            className="justify-start"
            onClick={() => openWorkspace({ type: "timeline" })}
          >
            <FilmIcon className="size-3.5" />
            Film — attentes & arrêts
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className="justify-start"
            onClick={() => openWorkspace({ type: "map" })}
          >
            <MapIcon className="size-3.5" />
            Carte — zones en tension
          </Button>
        </div>
      </div>

      {appliedCount > 0 && (
        <div className="rounded-xl border border-success/25 bg-success/5 p-4">
          <h2 className="text-[12px] font-semibold text-success">
            Plan appliqué · {appliedCount}
          </h2>
          <ul className="mt-2 flex flex-col gap-1 text-[11px] text-foreground/85">
            {appliedTitles.map((t) => (
              <li key={t} className="flex gap-1.5">
                <span className="text-success">✓</span>
                <span className="line-clamp-2">{t}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[10px] text-muted-2">Aperçu local — non envoyé au FMS</p>
        </div>
      )}
    </aside>
  )
}

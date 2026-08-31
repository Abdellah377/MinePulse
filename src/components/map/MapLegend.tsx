import { EQUIPMENT_TYPE_LABEL, type EquipmentType } from "@/lib/mock/types"
import { FILM_GROUP_CONFIG } from "@/lib/status"
import { FILM_STATE_GROUP_LABEL, type FilmStateGroup } from "@/lib/mock/types"
import { ROAD_STATUS_PAINT } from "@/lib/map/roadStyle"

const TYPES: EquipmentType[] = [
  "haul_truck",
  "excavator",
  "loader",
  "dozer",
  "drill",
  "grader",
]

const GROUPS = Object.keys(FILM_STATE_GROUP_LABEL) as FilmStateGroup[]

export function MapLegend({ showRoads = false }: { showRoads?: boolean }) {
  return (
    <div className="absolute bottom-8 left-3 z-10 max-w-[220px] rounded-md border border-border bg-surface/95 px-2.5 py-2 shadow-sm backdrop-blur-sm">
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-2">
        Légende
      </p>
      <div className="mb-2 flex flex-wrap gap-x-2 gap-y-1">
        {TYPES.map((t) => (
          <span key={t} className="text-[10px] text-muted">
            {EQUIPMENT_TYPE_LABEL[t]}
          </span>
        ))}
      </div>
      <div className="flex flex-col gap-0.5">
        {GROUPS.map((g) => {
          const cfg = FILM_GROUP_CONFIG[g]
          return (
            <div key={g} className="flex items-center gap-1.5 text-[10px] text-foreground/80">
              <span className={`size-2 shrink-0 rounded-full ${cfg.dot}`} />
              {cfg.label}
            </div>
          )
        })}
      </div>
      {showRoads && (
        <div className="mt-2 border-t border-border pt-1.5">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-2">Pistes</p>
          <div className="flex flex-col gap-0.5 text-[10px] text-foreground/80">
            <span className="flex items-center gap-1.5">
              <span className="h-0.5 w-4 shrink-0 rounded-sm" style={{ background: ROAD_STATUS_PAINT.OPEN.color }} />
              Ouverte
            </span>
            <span className="flex items-center gap-1.5">
              <span
                className="w-4 shrink-0 border-t-2 border-dashed"
                style={{ borderColor: ROAD_STATUS_PAINT.RESTRICTED.color }}
              />
              Restreinte
            </span>
            <span className="flex items-center gap-1.5">
              <span
                className="w-4 shrink-0 border-t-2 border-dashed"
                style={{ borderColor: ROAD_STATUS_PAINT.CLOSED.color }}
              />
              Fermée
            </span>
          </div>
        </div>
      )}
      <p className="mt-1.5 text-[9px] text-muted-2">
        Icône = type · couleur = statut{showRoads ? " · trait = piste" : ""}
      </p>
    </div>
  )
}

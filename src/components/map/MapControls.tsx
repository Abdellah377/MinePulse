import type { ReactNode } from "react"
import {
  ZoomIn,
  ZoomOut,
  Compass,
  Maximize2,
  Layers,
  Pencil,
  Plus,
  X,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { BASEMAP_STYLES } from "@/features/map/map.constants"
import type { BasemapId } from "@/features/map/map.types"
import { useMineMap } from "@/components/map/MineMapContext"
import { fitBoundsFromEquipment } from "@/features/map/map.utils"
import type { Equipment } from "@/lib/mock/types"

export function MapControls({
  basemap,
  onBasemapChange,
  editMode,
  onToggleEdit,
  onAddZone,
  isDrawing,
  fitEquipment,
}: {
  basemap: BasemapId
  onBasemapChange: (id: BasemapId) => void
  editMode: boolean
  onToggleEdit: () => void
  onAddZone?: () => void
  isDrawing?: boolean
  fitEquipment: Equipment[]
}) {
  const { map, mapRef } = useMineMap()
  const mapInstance = map ?? mapRef.current

  return (
    <div className="map-controls-root pointer-events-auto absolute left-3 top-3 z-20 flex flex-col gap-2">
      <div className="flex flex-col overflow-hidden rounded-md border border-border bg-surface shadow-sm">
        <CtrlBtn label="Zoom avant" onClick={() => mapInstance?.zoomIn({ duration: 200 })}>
          <ZoomIn className="size-3.5" />
        </CtrlBtn>
        <CtrlBtn
          label="Zoom arrière"
          onClick={() => mapInstance?.zoomOut({ duration: 200 })}
          border
        >
          <ZoomOut className="size-3.5" />
        </CtrlBtn>
        <CtrlBtn
          label="Nord"
          onClick={() => mapInstance?.easeTo({ bearing: 0, pitch: 0, duration: 300 })}
          border
        >
          <Compass className="size-3.5" />
        </CtrlBtn>
        <CtrlBtn
          label="Cadre engins"
          onClick={() => {
            const bounds = fitBoundsFromEquipment(fitEquipment)
            if (!mapInstance || !bounds) return
            mapInstance.fitBounds(bounds, { padding: 56, duration: 500, maxZoom: 16.5 })
          }}
          border
        >
          <Maximize2 className="size-3.5" />
        </CtrlBtn>
        {onAddZone && (
          <CtrlBtn label="Nouvelle zone" onClick={onAddZone} border active={isDrawing}>
            <Plus className="size-3.5" />
          </CtrlBtn>
        )}
        <CtrlBtn
          label={editMode ? "Quitter édition" : "Modifier les zones"}
          onClick={onToggleEdit}
          border
          active={editMode}
        >
          {editMode ? <X className="size-3.5" /> : <Pencil className="size-3.5" />}
        </CtrlBtn>
      </div>

      <div className="overflow-hidden rounded-md border border-border bg-surface shadow-sm">
        <div className="flex items-center gap-1 border-b border-border px-2 py-1 text-[10px] font-semibold uppercase text-muted-2">
          <Layers className="size-3" />
          Fond
        </div>
        {(Object.keys(BASEMAP_STYLES) as BasemapId[]).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onBasemapChange(id)}
            className={cn(
              "block w-full px-2.5 py-1.5 text-left text-[11px] transition-colors",
              basemap === id
                ? "bg-accent-soft font-semibold text-accent"
                : "text-foreground/80 hover:bg-surface-2"
            )}
          >
            {BASEMAP_STYLES[id].label}
          </button>
        ))}
      </div>
    </div>
  )
}

function CtrlBtn({
  children,
  onClick,
  label,
  border,
  active,
}: {
  children: ReactNode
  onClick: () => void
  label: string
  border?: boolean
  active?: boolean
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "flex size-8 items-center justify-center text-foreground/80 transition-colors hover:bg-surface-2",
        border && "border-t border-border",
        active && "bg-accent text-white hover:bg-accent"
      )}
    >
      {children}
    </button>
  )
}

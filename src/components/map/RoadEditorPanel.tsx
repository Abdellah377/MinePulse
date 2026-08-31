import { Plus, Save, Trash2, Undo2, X } from "lucide-react"

import type { RoutePath, Zone } from "@/lib/mock/types"
import {
  ROAD_STATUS_LABEL,
  ROAD_STATUS_REASON_LABEL,
  type RoadStatus,
  type RoadStatusReason,
} from "@/lib/map/roadNetwork"
import { cn } from "@/lib/utils"
import { useApiMode } from "@/lib/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { MapTool } from "@/features/map/map.types"

export interface RoadDraft {
  code: string
  name: string
  fromZoneId: string
  toZoneId: string
  distanceKm: number | null
  speedLimitKmh: number | null
  description: string
  status: RoadStatus
  statusReason: RoadStatusReason | null
  statusNote: string
}

const ROAD_TOOLS: { id: MapTool; label: string }[] = [
  { id: "select", label: "Sélection" },
  { id: "polyline", label: "Tracé" },
  { id: "delete", label: "Supprimer" },
]

export function RoadEditorToolbar({
  activeTool,
  onToolChange,
}: {
  activeTool: MapTool
  onToolChange: (tool: MapTool) => void
}) {
  return (
    <div className="flex items-center gap-1 border-b border-border bg-surface px-3 py-1.5">
      <span className="mr-1 text-[10px] font-semibold uppercase tracking-wide text-muted-2">
        Outils
      </span>
      {ROAD_TOOLS.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onToolChange(t.id)}
          className={cn(
            "rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors",
            activeTool === t.id
              ? "border-accent/40 bg-accent-soft text-accent"
              : "border-border-strong text-muted hover:bg-surface-2"
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function RoadListPanel({
  roads,
  selectedRoadId,
  onSelectRoad,
  onNewRoad,
  creating,
}: {
  roads: RoutePath[]
  selectedRoadId: string | null
  onSelectRoad: (id: string) => void
  onNewRoad: () => void
  creating: boolean
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-3 py-2.5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80">
          Routes ({roads.length})
        </h3>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {roads.map((r) => (
          <button
            key={r.id}
            type="button"
            onClick={() => onSelectRoad(r.id)}
            className={cn(
              "flex w-full flex-col border-b border-border px-3 py-2 text-left text-xs transition-colors",
              selectedRoadId === r.id ? "bg-accent-soft text-accent" : "text-foreground/85 hover:bg-surface-2"
            )}
          >
            <span className="truncate font-medium">{r.name || r.id}</span>
            <span className="text-[10px] text-muted-2">{ROAD_STATUS_LABEL[r.status ?? "OPEN"]}</span>
          </button>
        ))}
      </div>
      <div className="shrink-0 border-t border-border p-2">
        <Button variant={creating ? "secondary" : "outline"} size="sm" className="w-full" onClick={onNewRoad}>
          <Plus className="size-3.5" />
          Nouvelle route
        </Button>
      </div>
    </div>
  )
}

export function RoadPropertiesPanel({
  draft,
  zones,
  onChange,
  onSave,
  onCancel,
  onDelete,
  onUndoPoint,
  isCreating,
  canFinishDraft,
  pointCount,
}: {
  draft: RoadDraft | null
  zones: Zone[]
  onChange: (patch: Partial<RoadDraft>) => void
  onSave: () => void
  onCancel: () => void
  onDelete?: () => void
  onUndoPoint?: () => void
  isCreating: boolean
  canFinishDraft: boolean
  pointCount: number
}) {
  if (!draft) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <p className="text-xs text-muted">
          Sélectionnez une route, ou tracez une polyligne sur la carte (2 points minimum).
        </p>
      </div>
    )
  }

  const showReason = draft.status !== "OPEN"

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80">Propriétés</h3>
      {isCreating && (
        <div className="rounded-md border border-accent/25 bg-accent-soft px-2.5 py-2 text-[11px] text-accent">
          <p className="font-medium">Tracé en cours</p>
          <p className="mt-1 text-accent/90">
            Cliquez sur la carte ({pointCount} point{pointCount !== 1 ? "s" : ""}, minimum 2).
          </p>
          {pointCount > 0 && onUndoPoint && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-2 h-7 w-full border-accent/30 bg-surface text-[11px] text-accent hover:bg-surface-2"
              onClick={onUndoPoint}
            >
              <Undo2 className="size-3" />
              Annuler le dernier point
            </Button>
          )}
        </div>
      )}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Code</label>
        <Input
          value={draft.code}
          disabled={!isCreating}
          onChange={(e) => onChange({ code: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Nom</label>
        <Input value={draft.name} onChange={(e) => onChange({ name: e.target.value })} />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">De</label>
        <Select value={draft.fromZoneId || "__none"} onValueChange={(v) => onChange({ fromZoneId: v === "__none" ? "" : v })}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Zone origine" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none">Non renseignée</SelectItem>
            {zones.map((z) => (
              <SelectItem key={z.id} value={z.id}>
                {z.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Vers</label>
        <Select value={draft.toZoneId || "__none"} onValueChange={(v) => onChange({ toZoneId: v === "__none" ? "" : v })}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Zone destination" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none">Non renseignée</SelectItem>
            {zones.map((z) => (
              <SelectItem key={z.id} value={z.id}>
                {z.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Vitesse max (km/h)</label>
        <Input
          type="number"
          min={0}
          value={draft.speedLimitKmh ?? ""}
          placeholder="Non renseignée"
          onChange={(e) => onChange({ speedLimitKmh: e.target.value === "" ? null : Number(e.target.value) })}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Statut</label>
        <div className="flex flex-col gap-1">
          {(Object.keys(ROAD_STATUS_LABEL) as RoadStatus[]).map((status) => (
            <label key={status} className="flex items-center gap-2 text-[11px]">
              <input
                type="radio"
                name="road-status"
                checked={draft.status === status}
                onChange={() =>
                  onChange({
                    status,
                    statusReason: status === "OPEN" ? null : draft.statusReason,
                    statusNote: status === "OPEN" ? "" : draft.statusNote,
                  })
                }
                className="size-3.5 accent-accent"
              />
              {ROAD_STATUS_LABEL[status]}
            </label>
          ))}
        </div>
      </div>
      {showReason && (
        <>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Motif</label>
            <Select
              value={draft.statusReason ?? "__none"}
              onValueChange={(v) => onChange({ statusReason: v === "__none" ? null : (v as RoadStatusReason) })}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Optionnel" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none">Non renseigné</SelectItem>
                {(Object.keys(ROAD_STATUS_REASON_LABEL) as RoadStatusReason[]).map((reason) => (
                  <SelectItem key={reason} value={reason}>
                    {ROAD_STATUS_REASON_LABEL[reason]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Note</label>
            <Textarea rows={2} value={draft.statusNote} onChange={(e) => onChange({ statusNote: e.target.value })} />
          </div>
        </>
      )}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Description</label>
        <Textarea rows={2} value={draft.description} onChange={(e) => onChange({ description: e.target.value })} />
      </div>
      <div className="mt-auto flex flex-col gap-2 pt-2">
        <p className="text-[10px] text-muted-2">
          {useApiMode ? "Routes enregistrées par l’API opérationnelle." : "Routes de démonstration persistées localement."}
        </p>
        <Button size="sm" onClick={onSave} disabled={isCreating && !canFinishDraft}>
          <Save className="size-3.5" />
          {isCreating ? "Créer la route" : "Enregistrer"}
        </Button>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="flex-1" onClick={onCancel}>
            <X className="size-3.5" />
            Annuler
          </Button>
          {!isCreating && onDelete && (
            <Button variant="outline" size="sm" className="flex-1 text-danger hover:text-danger" onClick={onDelete}>
              <Trash2 className="size-3.5" />
              Supprimer
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

export function emptyRoadDraft(): RoadDraft {
  return {
    code: "",
    name: "",
    fromZoneId: "",
    toZoneId: "",
    distanceKm: null,
    speedLimitKmh: null,
    description: "",
    status: "OPEN",
    statusReason: null,
    statusNote: "",
  }
}

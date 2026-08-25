import { Plus, Save, Trash2, Undo2, X } from "lucide-react"

import type { Zone, ZoneType } from "@/lib/mock/types"
import { ZONE_TYPE_LABEL } from "@/lib/mock/types"
import { cn } from "@/lib/utils"
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

export interface ZoneDraft {
  name: string
  type: ZoneType
  color: string
  description: string
  capacity: number
}

const ZONE_TYPES = Object.keys(ZONE_TYPE_LABEL) as ZoneType[]
const SWATCHES = ["#2F6FED", "#8A6D3B", "#6B4FBF", "#D97706", "#5B7C99", "#7C8B84", "#C0392B", "#00843D"]

const TOOLS: { id: MapTool; label: string }[] = [
  { id: "select", label: "Sélection" },
  { id: "polygon", label: "Polygone" },
  { id: "vertex", label: "Éditer sommets" },
  { id: "delete", label: "Supprimer" },
]

export function ZoneEditorToolbar({
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
      {TOOLS.map((t) => (
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

export function ZoneListPanel({
  zones,
  selectedZoneId,
  onSelectZone,
  onNewZone,
  creating,
}: {
  zones: Zone[]
  selectedZoneId: string | null
  onSelectZone: (id: string) => void
  onNewZone: () => void
  creating: boolean
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-3 py-2.5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80">
          Zones ({zones.length})
        </h3>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {zones.map((z) => (
          <button
            key={z.id}
            onClick={() => onSelectZone(z.id)}
            className={cn(
              "flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left text-xs transition-colors",
              selectedZoneId === z.id ? "bg-accent-soft text-accent" : "text-foreground/85 hover:bg-surface-2"
            )}
          >
            <span className="size-2.5 shrink-0 rounded-sm" style={{ backgroundColor: z.color }} />
            <span className="min-w-0 flex-1 truncate">{z.name}</span>
            <span className="shrink-0 text-[10px] text-muted-2">{ZONE_TYPE_LABEL[z.type]}</span>
          </button>
        ))}
      </div>
      <div className="shrink-0 border-t border-border p-2">
        <Button
          variant={creating ? "secondary" : "outline"}
          size="sm"
          className="w-full"
          onClick={onNewZone}
        >
          <Plus className="size-3.5" />
          Nouvelle zone
        </Button>
      </div>
    </div>
  )
}

export function ZonePropertiesPanel({
  draft,
  onChange,
  onSave,
  onCancel,
  onDelete,
  onUndoPoint,
  isCreating,
  isEditingVertices,
  canFinishDraft,
  pointCount,
}: {
  draft: ZoneDraft | null
  onChange: (patch: Partial<ZoneDraft>) => void
  onSave: () => void
  onCancel: () => void
  onDelete?: () => void
  onUndoPoint?: () => void
  isCreating: boolean
  isEditingVertices?: boolean
  canFinishDraft: boolean
  pointCount: number
}) {
  if (!draft) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <p className="text-xs text-muted">
          Sélectionnez une zone dans la liste, ou appuyez sur <strong>+</strong> puis cliquez sur la
          carte pour dessiner un polygone.
        </p>
        <p className="text-[10px] text-muted-2">
          Nom, type, couleur et description alimentent le raisonnement IA (congestion, capacité,
          contexte opérationnel).
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80">
        Propriétés
      </h3>
      {isCreating && (
        <div className="rounded-md border border-accent/25 bg-accent-soft px-2.5 py-2 text-[11px] text-accent">
          <p className="font-medium">Dessin en cours</p>
          <p className="mt-1 text-accent/90">
            Cliquez sur la carte pour placer les sommets ({pointCount} point{pointCount !== 1 ? "s" : ""}
            , minimum 3). Double-clic pour terminer le contour.
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
      {isEditingVertices && !isCreating && (
        <p className="rounded-md border border-border bg-surface-2 px-2.5 py-2 text-[11px] text-muted">
          Glissez les sommets sur la carte pour ajuster la forme, puis enregistrez.
        </p>
      )}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Nom</label>
        <Input value={draft.name} onChange={(e) => onChange({ name: e.target.value })} />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Type</label>
        <Select value={draft.type} onValueChange={(v) => onChange({ type: v as ZoneType })}>
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ZONE_TYPES.map((t) => (
              <SelectItem key={t} value={t}>
                {ZONE_TYPE_LABEL[t]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">Couleur</label>
        <div className="flex flex-wrap gap-1.5">
          {SWATCHES.map((c) => (
            <button
              key={c}
              onClick={() => onChange({ color: c })}
              className={cn(
                "size-6 rounded-sm border-2 transition-transform",
                draft.color === c ? "scale-110 border-foreground" : "border-transparent"
              )}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          Capacité (file)
        </label>
        <Input
          type="number"
          min={0}
          value={draft.capacity}
          onChange={(e) => onChange({ capacity: Number(e.target.value) || 0 })}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          Description
        </label>
        <Textarea
          rows={3}
          value={draft.description}
          onChange={(e) => onChange({ description: e.target.value })}
        />
      </div>

      <div className="mt-auto flex flex-col gap-2 pt-2">
        <p className="text-[10px] text-muted-2">
          Zones persistées localement — utilisées par l&apos;agent IA pour le contexte opérationnel.
        </p>
        <Button size="sm" onClick={onSave} disabled={isCreating && !canFinishDraft}>
          <Save className="size-3.5" />
          {isCreating ? "Créer la zone" : "Enregistrer"}
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

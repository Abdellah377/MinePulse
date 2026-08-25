import type { AlertSeverity, EquipmentState, FilmStateGroup } from "@/lib/mock/types"
import { FILM_STATE_GROUP, EQUIPMENT_STATE_LABEL, FILM_STATE_GROUP_LABEL } from "@/lib/mock/types"
import { EQUIPMENT_ICON_SRC } from "@/lib/equipment-icons"

interface StateVisual {
  label: string
  color: string
  dot: string
  bg: string
}

export const FILM_GROUP_CONFIG: Record<FilmStateGroup, StateVisual> = {
  mouvement_charge: {
    label: FILM_STATE_GROUP_LABEL.mouvement_charge,
    color: "text-state-mouvement-charge",
    dot: "bg-state-mouvement-charge",
    bg: "bg-state-mouvement-charge/10",
  },
  mouvement_vide: {
    label: FILM_STATE_GROUP_LABEL.mouvement_vide,
    color: "text-state-mouvement-vide",
    dot: "bg-state-mouvement-vide",
    bg: "bg-state-mouvement-vide/10",
  },
  attente: {
    label: FILM_STATE_GROUP_LABEL.attente,
    color: "text-state-attente",
    dot: "bg-state-attente",
    bg: "bg-state-attente/10",
  },
  chargement_dechargement: {
    label: FILM_STATE_GROUP_LABEL.chargement_dechargement,
    color: "text-state-chargement",
    dot: "bg-state-chargement",
    bg: "bg-state-chargement/10",
  },
  arret: {
    label: FILM_STATE_GROUP_LABEL.arret,
    color: "text-state-arret",
    dot: "bg-state-arret",
    bg: "bg-state-arret/10",
  },
  eteint: {
    label: FILM_STATE_GROUP_LABEL.eteint,
    color: "text-state-eteint",
    dot: "bg-state-eteint",
    bg: "bg-state-eteint/10",
  },
  aucune_donnee: {
    label: FILM_STATE_GROUP_LABEL.aucune_donnee,
    color: "text-state-aucune-donnee",
    dot: "bg-state-aucune-donnee",
    bg: "bg-state-aucune-donnee/10",
  },
  indetermine: {
    label: FILM_STATE_GROUP_LABEL.indetermine,
    color: "text-state-indetermine",
    dot: "bg-state-indetermine",
    bg: "bg-state-indetermine/10",
  },
}

/** Per-state visual config (precise equipment state), colored via its Film legend group. */
export const STATE_CONFIG: Record<EquipmentState, StateVisual> = Object.fromEntries(
  (Object.keys(EQUIPMENT_STATE_LABEL) as EquipmentState[]).map((state) => {
    const group = FILM_GROUP_CONFIG[FILM_STATE_GROUP[state]]
    return [state, { ...group, label: EQUIPMENT_STATE_LABEL[state] }]
  })
) as Record<EquipmentState, StateVisual>

export const SEVERITY_CONFIG: Record<
  AlertSeverity,
  { label: string; color: string; dot: string; bg: string; border: string }
> = {
  critical: {
    label: "Critique",
    color: "text-severity-critical",
    dot: "bg-severity-critical",
    bg: "bg-severity-critical/10",
    border: "border-severity-critical/30",
  },
  warning: {
    label: "Warning",
    color: "text-severity-warning",
    dot: "bg-severity-warning",
    bg: "bg-severity-warning/10",
    border: "border-severity-warning/30",
  },
  info: {
    label: "Info",
    color: "text-severity-info",
    dot: "bg-severity-info",
    bg: "bg-severity-info/10",
    border: "border-severity-info/30",
  },
}

/** @deprecated Use `<EquipmentTypeIcon type={...} />` — kept for legacy imports. */
export const EQUIPMENT_ICON_SRC_BY_TYPE = EQUIPMENT_ICON_SRC

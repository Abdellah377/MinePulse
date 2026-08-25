import type { OemDiagnosticTab, OemFamily, OemMaintenanceTab, OemView } from "@/lib/workspace/types"

export type OemCol = {
  id: string
  header: string
  defaultVisible?: boolean
  unavailable?: boolean
  unavailableReason?: string
  align?: "left" | "right"
  tone?: "delay" | "alarm-red" | "alarm-yellow"
}

export type OemPeriodMode = "shift" | "posts" | "custom"

export type OemDraft = {
  equipmentCodes: string[]
  equipmentType: string
  equipmentSearch: string
  periodMode: OemPeriodMode
  fromDate: string
  toDate: string
  fromShift: string
  toShift: string
  from: string
  to: string
  parameterKeys: string[]
  parameterSearch: string
  tyrePositions: string[]
  minDelaySec: number
  severity: string
  category: string
  statusFilter: string
}

export const DEFAULT_OEM_DRAFT: OemDraft = {
  equipmentCodes: [],
  equipmentType: "all",
  equipmentSearch: "",
  periodMode: "shift",
  fromDate: "",
  toDate: "",
  fromShift: "",
  toShift: "",
  from: "",
  to: "",
  parameterKeys: [],
  parameterSearch: "",
  tyrePositions: ["FL", "FR", "R1L", "R1R", "R2L", "R2R"],
  minDelaySec: 30,
  severity: "all",
  category: "all",
  statusFilter: "all",
}

export const OEM_FAMILIES: Array<{
  id: OemFamily
  label: string
  /** Direct click opens the single interface; submenu lists Courbes views. */
  direct?: boolean
  views: Array<{ id: OemView; label: string }>
}> = [
  {
    id: "connectivite",
    label: "Connectivité",
    direct: true,
    views: [{ id: "connectivite", label: "Connectivité" }],
  },
  {
    id: "diagnostic",
    label: "Diagnostic machine",
    direct: true,
    views: [{ id: "diagnostic", label: "Diagnostic machine" }],
  },
  {
    id: "maintenance",
    label: "Maintenance",
    direct: true,
    views: [{ id: "maintenance", label: "Maintenance" }],
  },
  {
    id: "courbes",
    label: "Courbes capteurs",
    views: [
      { id: "pneus", label: "Pression / température pneus" },
      { id: "vitesse-gasoil", label: "Vitesse / gasoil" },
      { id: "poids", label: "Poids / vitesse / carburant" },
      { id: "multi", label: "Multi-paramètres" },
    ],
  },
]

const LEGACY_OEM_VIEW: Record<string, OemView> = {
  ping: "connectivite",
  controle: "connectivite",
  retard: "connectivite",
  parametres: "diagnostic",
  erreurs: "diagnostic",
  analyse: "diagnostic",
  indicateurs: "maintenance",
  alarmes: "maintenance",
}

export function resolveOemView(raw: string | undefined | null): OemView {
  if (!raw) return "connectivite"
  if (raw in LEGACY_OEM_VIEW) return LEGACY_OEM_VIEW[raw]
  if (
    raw === "connectivite" ||
    raw === "diagnostic" ||
    raw === "maintenance" ||
    raw === "pneus" ||
    raw === "vitesse-gasoil" ||
    raw === "poids" ||
    raw === "multi"
  ) {
    return raw
  }
  return "connectivite"
}

export function oemFamilyForView(view: OemView): OemFamily {
  if (view === "connectivite") return "connectivite"
  if (view === "diagnostic") return "diagnostic"
  if (view === "maintenance") return "maintenance"
  return "courbes"
}

export function defaultDiagnosticTab(raw: string | undefined | null): OemDiagnosticTab {
  if (raw === "erreurs" || raw === "analyse") return raw
  return "parametres"
}

export function defaultMaintenanceTab(raw: string | undefined | null): OemMaintenanceTab {
  if (raw === "alarmes") return raw
  return "indicateurs"
}

export const OEM_TYPE_GROUP: Record<string, string> = {
  haul_truck: "Camions",
  excavator: "Pelles",
  loader: "Chargeuses",
  dozer: "Bulldozers",
  drill: "Sondeuses",
  grader: "Niveleuses",
  water_truck: "Camions citerne",
  light_vehicle: "Véhicules légers",
  other: "Autres",
}

export const UNAVAILABLE_SIM = "Indisponible en simulation"

export type WorkspaceModule = "alertes" | "actions" | "performance" | "oem" | "parametres"

export type WorkspaceType =
  | "alerts"
  | "map"
  | "timeline"
  | "performance"
  | "oem"
  | "actions"
  | "settings"

export type OemFamily = "connectivite" | "diagnostic" | "maintenance" | "courbes"

/** The 7 user-facing OEM interfaces (workspace identity). */
export type OemView =
  | "connectivite"
  | "diagnostic"
  | "maintenance"
  | "pneus"
  | "vitesse-gasoil"
  | "poids"
  | "multi"

export type OemDiagnosticTab = "parametres" | "erreurs" | "analyse"
export type OemMaintenanceTab = "indicateurs" | "alarmes"

export type PerformanceMetric =
  | "production"
  | "fuel"
  | "cycle"
  | "waiting"
  | "td"
  | "tu"
  | "downtime"
  | "voyages"

export interface WorkspaceContext {
  equipmentId?: string
  equipmentCode?: string
  zoneId?: string
  zoneName?: string
  alertId?: string
  predictionId?: string
  metric?: PerformanceMetric
  investigationId?: string
  oemFamily?: OemFamily
  oemView?: OemView
  mapFocusAt?: number
  /** Canonical module-home workspace. Survives incidental selection patches. */
  _home?: boolean
  /** Intentional duplicate from duplicateTab(). */
  _dup?: number | string
  [key: string]: unknown
}

export interface WorkspaceTab {
  id: string
  type: WorkspaceType
  title: string
  module: WorkspaceModule
  context: WorkspaceContext
  investigationId?: string
  isPinned: boolean
  isDirty: boolean
  createdAt: number
  lastActivatedAt: number
}

export interface OpenWorkspaceInput {
  type: WorkspaceType
  context?: WorkspaceContext
  title?: string
  investigationId?: string
  pin?: boolean
}

export const WORKSPACE_TYPE_MODULE: Record<WorkspaceType, WorkspaceModule> = {
  alerts: "alertes",
  map: "alertes",
  timeline: "alertes",
  performance: "performance",
  oem: "oem",
  actions: "actions",
  settings: "parametres",
}

export const MODULE_HOME: Record<
  WorkspaceModule,
  { type: WorkspaceType; title: string; context?: WorkspaceContext }
> = {
  alertes: { type: "alerts", title: "Alertes IA", context: { _home: true } },
  actions: { type: "actions", title: "Actions IA", context: { _home: true } },
  performance: {
    type: "performance",
    title: "Performance — Production",
    context: { metric: "production", _home: true },
  },
  oem: {
    type: "oem",
    title: "Connectivité",
    context: { oemFamily: "connectivite", oemView: "connectivite", _home: true },
  },
  parametres: { type: "settings", title: "Paramètres", context: { _home: true } },
}

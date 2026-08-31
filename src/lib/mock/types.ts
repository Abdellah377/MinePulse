export type EquipmentType =
  | "haul_truck"
  | "excavator"
  | "loader"
  | "dozer"
  | "drill"
  | "grader"
  | "water_truck"
  | "light_vehicle"
  | "other"

/** Cycle + exception vocabulary (kept in French to match operator habits). */
export type EquipmentState =
  | "mouvement_charge"
  | "mouvement_vide"
  | "attente_charge"
  | "chargement"
  | "attente_dechargement"
  | "dechargement"
  | "arret_exploitation"
  | "arret_materiel"
  | "arret_exterieur"
  | "arret_indetermine"
  | "eteint"
  | "aucune_donnee"
  | "indetermine"
  | "ravitaillement"
  | "parking"

/** The 8 colors shown in the Film legend — several EquipmentState values share a group. */
export type FilmStateGroup =
  | "mouvement_charge"
  | "mouvement_vide"
  | "attente"
  | "chargement_dechargement"
  | "arret"
  | "eteint"
  | "aucune_donnee"
  | "indetermine"

export const FILM_STATE_GROUP: Record<EquipmentState, FilmStateGroup> = {
  mouvement_charge: "mouvement_charge",
  mouvement_vide: "mouvement_vide",
  attente_charge: "attente",
  attente_dechargement: "attente",
  chargement: "chargement_dechargement",
  dechargement: "chargement_dechargement",
  arret_exploitation: "arret",
  arret_materiel: "arret",
  arret_exterieur: "arret",
  arret_indetermine: "arret",
  eteint: "eteint",
  aucune_donnee: "aucune_donnee",
  indetermine: "indetermine",
  ravitaillement: "attente",
  parking: "arret",
}

export const EQUIPMENT_STATE_LABEL: Record<EquipmentState, string> = {
  mouvement_charge: "Mouvement à charge",
  mouvement_vide: "Mouvement à vide",
  attente_charge: "Attente de chargement",
  chargement: "Chargement",
  attente_dechargement: "Attente de déchargement",
  dechargement: "Déchargement",
  arret_exploitation: "Arrêt exploitation",
  arret_materiel: "Arrêt matériel",
  arret_exterieur: "Arrêt extérieur",
  arret_indetermine: "Arrêt non défini",
  eteint: "Éteint",
  aucune_donnee: "Aucune donnée",
  indetermine: "Non déterminé",
  ravitaillement: "Ravitaillement",
  parking: "Parking",
}

export const FILM_STATE_GROUP_LABEL: Record<FilmStateGroup, string> = {
  mouvement_charge: "Mouvement à charge",
  mouvement_vide: "Mouvement à vide",
  attente: "Attente",
  chargement_dechargement: "Chargement / Déchargement",
  arret: "Arrêt",
  eteint: "Éteint",
  aucune_donnee: "Aucune donnée",
  indetermine: "Non déterminé",
}

export const EQUIPMENT_TYPE_LABEL: Record<EquipmentType, string> = {
  haul_truck: "Camion",
  excavator: "Pelle",
  loader: "Chargeuse",
  dozer: "Bulldozer",
  drill: "Sondeuse",
  grader: "Niveleuse",
  water_truck: "Camion citerne",
  light_vehicle: "Véhicule léger",
  other: "Autre",
}

export interface Vec2 {
  x: number
  y: number
}

/** The 6 stages of a truck's current cycle, in order ("Cycle actuel"). */
export type CycleStageKey =
  | "vide"
  | "attente_charge"
  | "chargement"
  | "charge"
  | "attente_dechargement"
  | "dechargement"

export const CYCLE_STAGE_LABEL: Record<CycleStageKey, string> = {
  vide: "Vide",
  attente_charge: "Attente charge",
  chargement: "Chargement",
  charge: "Chargé",
  attente_dechargement: "Attente déch.",
  dechargement: "Déchargement",
}

export const CYCLE_STAGE_ORDER: CycleStageKey[] = [
  "vide",
  "attente_charge",
  "chargement",
  "charge",
  "attente_dechargement",
  "dechargement",
]

export interface CycleStage {
  key: CycleStageKey
  minutes: number | null
  isCurrent: boolean
  isOutlier: boolean
}

export interface Equipment {
  /** Stable database identity in API mode; display codes are not database IDs. */
  databaseId?: number
  id: string
  code: string
  type: EquipmentType
  model: string
  state: EquipmentState
  position: Vec2 | null
  heading: number | null
  speedKmh: number | null
  fuelPct: number | null
  gasoilLph: number | null
  tdPct: number | null
  tuPct: number | null
  engineOn: boolean | null
  operatorId: string | null
  zoneId: string | null
  destinationZoneId: string | null
  payloadTons: number | null
  capacityTons: number | null
  odometerKm: number | null
  engineHours: number | null
  tripsThisShift: number
  waitingMinutesThisShift: number
  idleMinutesThisShift: number
  lastUpdate: number | null
  siteId: string
  healthScore: number | null
  cycleActuel: CycleStage[]
  cycleDureeMoyenneMin: number | null
}

export type OperatorStatus = "active" | "break" | "offline"

export interface Operator {
  id: string
  name: string
  badgeId: string
  certLevel: "Trainee" | "Certified" | "Senior"
  shiftId: string
  assignedEquipmentId: string | null
  cyclesThisShift: number
  idleMinutes: number
  performanceScore: number | null
  status: OperatorStatus
  siteId: string
}

export interface Shift {
  databaseId?: number
  windowStart?: string
  windowEnd?: string
  id: string
  name: string
  startHour: number
  endHour: number
  startMinute?: number
  endMinute?: number
}

export interface Pit {
  id: string
  name: string
}

export interface Site {
  databaseId?: number
  id: string
  name: string
  region: string | null
  pits: Pit[]
}

export type ZoneType =
  | "chargement"
  | "dechargement"
  | "concasseur"
  | "fuel"
  | "atelier"
  | "parking"
  | "restreinte"

export const ZONE_TYPE_LABEL: Record<ZoneType, string> = {
  chargement: "Chargement",
  dechargement: "Dump / Déchargement",
  concasseur: "Concasseur",
  fuel: "Station fuel",
  atelier: "Atelier",
  parking: "Parking",
  restreinte: "Zone restreinte",
}

export const ZONE_TYPE_COLOR: Record<ZoneType, string> = {
  chargement: "#2F6FED",
  dechargement: "#8A6D3B",
  concasseur: "#6B4FBF",
  fuel: "#D97706",
  atelier: "#5B7C99",
  parking: "#7C8B84",
  restreinte: "#C0392B",
}

export interface Zone {
  databaseId?: number
  id: string
  name: string
  type: ZoneType
  /** Legacy workspace coordinates (mock zones, AI context). */
  points: Vec2[]
  /** Map coordinates captured when drawing — preferred for rendering. */
  ringLngLat?: [number, number][]
  color: string
  description: string
  capacity: number | null
  siteId: string
}

export type RoadStatus = "OPEN" | "CLOSED" | "RESTRICTED"

export type RoadStatusReason =
  | "BLASTING"
  | "MAINTENANCE"
  | "ROAD_DAMAGE"
  | "FLOODING"
  | "CONGESTION_CONTROL"
  | "OTHER"

export interface RoutePath {
  id: string
  databaseId?: number
  name?: string | null
  fromZoneId: string
  toZoneId: string
  points: Vec2[]
  distanceKm: number | null
  siteId: string
  status?: RoadStatus
  speedLimitKmh?: number | null
  description?: string | null
  statusReason?: RoadStatusReason | null
  statusNote?: string | null
}

export type AlertSeverity = "critical" | "warning" | "info"
export type AlertStatus = "new" | "acknowledged" | "investigating" | "assigned" | "resolved"
export type AlertSource = "FMS" | "SENSOR" | "RULE" | "PREDICTION" | "AI"

export type AlertPredictionMeta = {
  probability?: number | null
  threshold?: number | null
  horizonMinutes?: number | null
  dataClass?: string | null
  modelVersion?: string | null
  modelType?: string | null
  topSignals?: string[] | null
  source?: string | null
}

export const ALERT_STATUS_LABEL: Record<AlertStatus, string> = {
  new: "Nouveau",
  acknowledged: "Acquitté",
  investigating: "En investigation",
  assigned: "Assigné",
  resolved: "Résolu",
}

export interface Alert {
  id: string
  severity: AlertSeverity
  status: AlertStatus
  title: string
  description: string
  equipmentId: string | null
  zoneId: string | null
  location: string
  category: string
  /** Operational event time. Legacy/mock records may fall back to createdAt. */
  occurredAt?: number | null
  /** Persistence time in API mode; historical mock time in demo mode. */
  createdAt: number
  updatedAt: number
  assignedTo: string | null
  resolution: string | null
  source?: AlertSource
  prediction?: AlertPredictionMeta | null
}

export interface TimelineSegment {
  id: string
  equipmentId: string
  state: EquipmentState
  start: number
  end: number
  zoneName: string | null
}

export interface ProductionRecord {
  label: string
  tonnage: number
  target: number | null
  targetCycleMin?: number | null
  attainmentPct?: number | null
  gapTons?: number | null
  gapPct?: number | null
  trips?: number | null
  delayMin?: number | null
}

export interface CycleTimeSample {
  equipmentType: EquipmentType
  bucket: string
  minutes: number
}

export interface DowntimeReason {
  reason: string
  hours: number
}

export function cycleTotalMinutes(stages: CycleStage[]): number {
  return stages.reduce((sum, s) => sum + (s.minutes ?? 0), 0)
}

export function zoneCentroid(zone: Pick<Zone, "points">): Vec2 {
  const n = zone.points.length || 1
  const sum = zone.points.reduce(
    (acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y }),
    { x: 0, y: 0 }
  )
  return { x: sum.x / n, y: sum.y / n }
}

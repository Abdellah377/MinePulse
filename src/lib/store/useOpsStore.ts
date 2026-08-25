import { create } from "zustand"

import {
  fetchBootstrap,
  fetchOperationalSettings,
  patchAlert,
  patchOperationalSettings,
  useApiMode,
  type OpsContext,
  type OperationalSettingsDto,
} from "@/lib/api/client"
import { mergeProductionByShift, type ProductionByShift } from "@/lib/production/mergeProduction"
import {
  connectionAfterEquipmentPoll,
  isFullWorldPayload,
  nextErrorAfterEquipmentPoll,
  nextErrorAfterFullHydrate,
  SETTINGS_LOAD_ERROR,
  shouldStampSuccessfulSync,
  withoutMatchingError,
} from "@/lib/store/apiSync"
import { sortEquipmentByCode } from "@/lib/equipmentOrder"
import { SHIFTS, SITES, generateMockWorld } from "@/lib/mock/generator"
import { SPOTLIGHT, SPOTLIGHT_CODES } from "@/lib/mock/scenario"
import { zoneCentroid } from "@/lib/mock/types"
import type {
  Alert,
  AlertStatus,
  Equipment,
  EquipmentState,
  Operator,
  RoutePath,
  Shift,
  Site,
  TimelineSegment,
  Zone,
} from "@/lib/mock/types"

const STATE_TRANSITIONS: Record<EquipmentState, EquipmentState[]> = {
  mouvement_charge: ["mouvement_charge", "mouvement_charge", "attente_dechargement", "mouvement_charge"],
  mouvement_vide: ["mouvement_vide", "mouvement_vide", "attente_charge", "mouvement_vide"],
  attente_charge: ["attente_charge", "chargement", "attente_charge"],
  chargement: ["chargement", "mouvement_charge"],
  attente_dechargement: ["attente_dechargement", "dechargement", "attente_dechargement"],
  dechargement: ["dechargement", "mouvement_vide"],
  arret_exploitation: ["arret_exploitation", "arret_exploitation", "mouvement_vide"],
  arret_materiel: ["arret_materiel", "arret_materiel", "arret_materiel", "eteint"],
  arret_exterieur: ["arret_exterieur", "arret_exterieur", "mouvement_vide"],
  arret_indetermine: ["arret_indetermine", "indetermine", "mouvement_vide"],
  eteint: ["eteint", "eteint", "arret_materiel"],
  aucune_donnee: ["aucune_donnee", "indetermine", "mouvement_vide"],
  indetermine: ["indetermine", "mouvement_vide", "arret_indetermine"],
  ravitaillement: ["ravitaillement", "mouvement_vide", "attente_charge"],
  parking: ["parking", "parking", "eteint"],
}

function isDownState(state: EquipmentState) {
  return state.startsWith("arret") || state === "eteint"
}

/** Spotlight units keep their narrative state; only mild position jitter. */
function jitterSpotlight(eq: Equipment): Equipment {
  if (!eq.position) return { ...eq, lastUpdate: Date.now() }
  return {
    ...eq,
    position: {
      x: eq.position.x + (Math.random() - 0.5) * 1.2,
      y: eq.position.y + (Math.random() - 0.5) * 1.2,
    },
    lastUpdate: Date.now(),
  }
}

function stepEquipment(eq: Equipment, zones: Zone[]): Equipment {
  if (useApiMode) return eq
  if (SPOTLIGHT_CODES.has(eq.code)) return jitterSpotlight(eq)

  // Keep Banc B congestion queue stable during live tick
  const zone = zones.find((z) => z.id === eq.zoneId)
  if (
    zone?.name === SPOTLIGHT.bancBName &&
    (eq.state === "attente_charge" || eq.state === "mouvement_vide")
  ) {
    return jitterSpotlight(eq)
  }

  const roll = Math.random()
  let nextState = eq.state
  if (roll < 0.12) {
    const options = STATE_TRANSITIONS[eq.state]
    nextState = options[Math.floor(Math.random() * options.length)]
  }

  const isMoving = nextState === "mouvement_charge" || nextState === "mouvement_vide"
  const speedTarget = isMoving
    ? nextState === "mouvement_charge"
      ? 18 + Math.random() * 16
      : 24 + Math.random() * 18
    : 0
  const speedKmh = (eq.speedKmh ?? 0) + (speedTarget - (eq.speedKmh ?? 0)) * 0.4

  const drift = isMoving ? 3.2 : 0.3
  const anchor = zones.length && eq.position
    ? zoneCentroid(zones[Math.floor(Math.random() * zones.length)])
    : eq.position ?? { x: 0, y: 0 }
  const dx = anchor.x - (eq.position?.x ?? anchor.x)
  const dy = anchor.y - (eq.position?.y ?? anchor.y)
  const dist = Math.max(1, Math.hypot(dx, dy))
  const position = isMoving && eq.position
    ? {
        x: eq.position.x + (dx / dist) * drift + (Math.random() - 0.5) * 1.5,
        y: eq.position.y + (dy / dist) * drift + (Math.random() - 0.5) * 1.5,
      }
    : eq.position

  const fuelDelta = eq.engineOn ? -Math.random() * 0.04 : 0
  const fuelPct = Math.max(4, Math.min(100, (eq.fuelPct ?? 50) + fuelDelta))

  return {
    ...eq,
    state: nextState,
    engineOn: !isDownState(nextState) ? true : nextState === "eteint" || nextState === "parking" ? false : eq.engineOn,
    speedKmh: Math.max(0, Number(speedKmh.toFixed(1))),
    position,
    heading: isMoving && eq.heading != null ? (eq.heading + (Math.random() - 0.5) * 20 + 360) % 360 : eq.heading,
    fuelPct: Number(fuelPct.toFixed(1)),
    payloadTons:
      nextState === "mouvement_charge"
        ? (eq.capacityTons ?? 0) * (0.85 + Math.random() * 0.17)
        : nextState === "chargement"
          ? eq.payloadTons
          : 0,
    tripsThisShift:
      eq.state !== "mouvement_charge" && nextState === "mouvement_charge"
        ? eq.tripsThisShift + 1
        : eq.tripsThisShift,
    waitingMinutesThisShift:
      nextState === "attente_charge" || nextState === "attente_dechargement"
        ? eq.waitingMinutesThisShift + 0.2
        : eq.waitingMinutesThisShift,
    idleMinutesThisShift: isDownState(nextState) ? eq.idleMinutesThisShift + 0.2 : eq.idleMinutesThisShift,
    lastUpdate: Date.now(),
  }
}

export type Density = "comfortable" | "compact"

interface OpsState {
  sites: Site[]
  shifts: Shift[]
  selectedSiteId: string
  selectedShiftId: string
  /** Inclusive analysis window (YYYY-MM-DD). */
  periodFrom: string
  periodTo: string
  zones: Zone[]
  routes: RoutePath[]
  equipment: Equipment[]
  operators: Operator[]
  alerts: Alert[]
  timelineSegments: TimelineSegment[]
  productionByShift: ProductionByShift
  cycleTimeSamples: ReturnType<typeof generateMockWorld>["cycleTimeSamples"]
  downtimeReasons: ReturnType<typeof generateMockWorld>["downtimeReasons"]
  lastSyncAt: number
  lastSuccessfulSyncAt: number | null
  idleAlertThresholdMin: number
  noCommThresholdMin: number
  cycleDurationThresholdMin: number
  density: Density
  unit: "metric" | "imperial"
  /** Simulation clock ISO from backend when VITE_USE_API — drives Film window. */
  simNowIso: string | null
  apiBootstrapped: boolean
  apiPollError: string | null
  apiConnectionState: "online" | "degraded" | "offline"
  /** True only after a bootstrap that included production + timeline. */
  fullWorldHydrated: boolean

  setSelectedSite: (id: string) => void
  setSelectedShift: (id: string) => void
  setPeriodRange: (from: string, to: string) => void
  tick: () => void
  updateAlertStatus: (id: string, status: AlertStatus, assignedTo?: string) => void
  applyOperationalSettings: (dto: OperationalSettingsDto) => void
  patchOperationalSetting: (key: keyof OperationalSettingsDto, value: number) => Promise<void>
  setIdleAlertThreshold: (min: number) => void
  setNoCommThreshold: (min: number) => void
  setCycleDurationThreshold: (min: number) => void
  setDensity: (d: Density) => void
  setUnit: (u: "metric" | "imperial") => void
  setZones: (updater: (zones: Zone[]) => Zone[]) => void
  setEquipment: (updater: (equipment: Equipment[]) => Equipment[]) => void
  hydrateWorld: (payload: {
    sites?: Site[]
    shifts?: Shift[]
    zones?: Zone[]
    routes?: RoutePath[]
    equipment?: Equipment[]
    operators?: Operator[]
    alerts?: Alert[]
    productionByShift?: OpsState["productionByShift"]
    timelineSegments?: TimelineSegment[]
    cycleTimeSamples?: OpsState["cycleTimeSamples"]
    downtimeReasons?: OpsState["downtimeReasons"]
    simNow?: string | null
    activeSiteCode?: string | null
    activeShiftId?: string | null
  }) => void
  hydrateFromApi: (payload: {
    equipment?: Equipment[]
    timelineSegments?: TimelineSegment[]
    productionByShift?: OpsState["productionByShift"]
    alerts?: Alert[]
    cycleTimeSamples?: OpsState["cycleTimeSamples"]
    downtimeReasons?: OpsState["downtimeReasons"]
    simNow?: string | null
  }) => void
  patchEquipment: (item: Equipment) => void
}

const world = useApiMode
  ? {
      zones: [] as Zone[],
      routes: [] as RoutePath[],
      equipment: [] as Equipment[],
      operators: [] as Operator[],
      alerts: [] as Alert[],
      timelineSegments: [] as TimelineSegment[],
      productionByShift: { hourly: [], daily: [], shiftly: [] } as ProductionByShift,
      cycleTimeSamples: [] as ReturnType<typeof generateMockWorld>["cycleTimeSamples"],
      downtimeReasons: [] as ReturnType<typeof generateMockWorld>["downtimeReasons"],
    }
  : generateMockWorld()

function todayIso() {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

const today = todayIso()

function apiCtx(state: Pick<OpsState, "selectedSiteId" | "selectedShiftId">): OpsContext {
  return { siteCode: state.selectedSiteId, shiftId: state.selectedShiftId }
}

function settingsFromDto(dto: OperationalSettingsDto) {
  return {
    idleAlertThresholdMin: dto.idle_alert_threshold_min,
    noCommThresholdMin: dto.no_comm_threshold_min,
    cycleDurationThresholdMin: dto.cycle_duration_threshold_min,
  }
}

export const useOpsStore = create<OpsState>((set, get) => ({
  sites: useApiMode ? [] : SITES,
  shifts: useApiMode ? [] : SHIFTS,
  selectedSiteId: useApiMode ? "" : SITES[0].id,
  selectedShiftId: useApiMode ? "" : SHIFTS[0].id,
  periodFrom: today,
  periodTo: today,
  zones: world.zones,
  routes: world.routes,
  equipment: world.equipment,
  operators: world.operators,
  alerts: world.alerts,
  timelineSegments: world.timelineSegments,
  productionByShift: useApiMode
    ? ({ hourly: [], daily: [], shiftly: [] } as ProductionByShift)
    : (world.productionByShift as ProductionByShift),
  cycleTimeSamples: world.cycleTimeSamples,
  downtimeReasons: world.downtimeReasons,
  lastSyncAt: Date.now(),
  lastSuccessfulSyncAt: useApiMode ? null : Date.now(),
  idleAlertThresholdMin: 15,
  noCommThresholdMin: 5,
  cycleDurationThresholdMin: 50,
  density: "compact",
  unit: "metric",
  simNowIso: null,
  apiBootstrapped: !useApiMode,
  apiPollError: null,
  apiConnectionState: useApiMode ? "offline" : "online",
  fullWorldHydrated: !useApiMode,

  setSelectedSite: (id) => set({ selectedSiteId: id }),
  setSelectedShift: (id) => set({ selectedShiftId: id }),
  setPeriodRange: (from, to) => {
    const periodFrom = from <= to ? from : to
    const periodTo = from <= to ? to : from
    set({ periodFrom, periodTo })
  },

  tick: () => {
    const { equipment, zones, selectedSiteId } = get()
    const nextEquipment = equipment.map((eq) =>
      eq.siteId === selectedSiteId ? stepEquipment(eq, zones.filter((z) => z.siteId === eq.siteId)) : eq
    )
    set({ equipment: nextEquipment, lastSyncAt: Date.now() })
  },

  updateAlertStatus: (id, status, assignedTo) => {
    if (!useApiMode) {
      set((s) => ({
        alerts: s.alerts.map((a) =>
          a.id === id
            ? { ...a, status, assignedTo: assignedTo ?? a.assignedTo, updatedAt: Date.now() }
            : a
        ),
      }))
      return
    }
    void patchAlert(
      id,
      { status, actor_label: assignedTo },
      apiCtx(get())
    )
      .then((dto) => {
        set((s) => ({
          alerts: s.alerts.map((a) => (a.id === dto.id ? dto : a)),
          apiPollError: withoutMatchingError(s.apiPollError, "Échec mise à jour alerte"),
        }))
      })
      .catch(() => {
        set({ apiPollError: "Échec mise à jour alerte" })
      })
  },

  applyOperationalSettings: (dto) =>
    set((s) => ({
      ...settingsFromDto(dto),
      apiPollError: withoutMatchingError(s.apiPollError, SETTINGS_LOAD_ERROR),
    })),

  patchOperationalSetting: async (key, value) => {
    if (!useApiMode) return
    const dto = await patchOperationalSettings({ [key]: value })
    get().applyOperationalSettings(dto)
  },

  setIdleAlertThreshold: (min) => set({ idleAlertThresholdMin: min }),
  setNoCommThreshold: (min) => set({ noCommThresholdMin: min }),
  setCycleDurationThreshold: (min) => set({ cycleDurationThresholdMin: min }),
  setDensity: (d) => set({ density: d }),
  setUnit: (u) => set({ unit: u }),
  setZones: (updater) => set((s) => ({ zones: updater(s.zones) })),
  setEquipment: (updater) => set((s) => ({ equipment: updater(s.equipment) })),

  hydrateWorld: (payload) =>
    set((s) => {
      const gotFull = isFullWorldPayload(payload)
      const fullWorldHydrated = gotFull || s.fullWorldHydrated
      const apiPollError = gotFull ? nextErrorAfterFullHydrate(s.apiPollError) : s.apiPollError
      const now = Date.now()
      const stamp = shouldStampSuccessfulSync({ fullWorldHydrated, apiPollError })
      return {
        sites: payload.sites ?? s.sites,
        shifts: payload.shifts ?? s.shifts,
        zones: payload.zones ?? s.zones,
        routes: payload.routes ?? s.routes,
        equipment: payload.equipment ? sortEquipmentByCode(payload.equipment) : s.equipment,
        operators: payload.operators ?? s.operators,
        alerts: payload.alerts ?? s.alerts,
        productionByShift: mergeProductionByShift(s.productionByShift, payload.productionByShift),
        timelineSegments: payload.timelineSegments ?? s.timelineSegments,
        cycleTimeSamples: payload.cycleTimeSamples ?? s.cycleTimeSamples,
        downtimeReasons: payload.downtimeReasons ?? s.downtimeReasons,
        selectedSiteId: s.apiBootstrapped
          ? s.selectedSiteId || payload.activeSiteCode || payload.sites?.[0]?.id || ""
          : payload.activeSiteCode || payload.sites?.[0]?.id || s.selectedSiteId,
        selectedShiftId: s.apiBootstrapped
          ? s.selectedShiftId || payload.activeShiftId || ""
          : payload.activeShiftId || payload.shifts?.[0]?.id || s.selectedShiftId,
        simNowIso: payload.simNow ?? s.simNowIso,
        apiBootstrapped: true,
        fullWorldHydrated,
        apiPollError,
        apiConnectionState: gotFull
          ? apiPollError
            ? "degraded"
            : "online"
          : s.apiConnectionState === "online"
            ? s.apiConnectionState
            : "degraded",
        lastSuccessfulSyncAt: stamp ? now : s.lastSuccessfulSyncAt,
        lastSyncAt: now,
      }
    }),

  hydrateFromApi: (payload) =>
    set((s) => {
      const apiPollError = nextErrorAfterEquipmentPoll(s.apiPollError)
      const stamp = shouldStampSuccessfulSync({
        fullWorldHydrated: s.fullWorldHydrated,
        apiPollError,
      })
      const now = Date.now()
      return {
        equipment: payload.equipment ? sortEquipmentByCode(payload.equipment) : s.equipment,
        timelineSegments: payload.timelineSegments ?? s.timelineSegments,
        productionByShift: mergeProductionByShift(s.productionByShift, payload.productionByShift),
        alerts: payload.alerts ?? s.alerts,
        cycleTimeSamples: payload.cycleTimeSamples ?? s.cycleTimeSamples,
        downtimeReasons: payload.downtimeReasons ?? s.downtimeReasons,
        simNowIso: payload.simNow ?? s.simNowIso,
        apiPollError,
        apiConnectionState: connectionAfterEquipmentPoll({
          fullWorldHydrated: s.fullWorldHydrated,
          apiPollError,
        }),
        lastSuccessfulSyncAt: stamp ? now : s.lastSuccessfulSyncAt,
        lastSyncAt: now,
      }
    }),

  patchEquipment: (item) =>
    set((s) => ({
      equipment: sortEquipmentByCode(
        s.equipment.some((e) => e.id === item.id)
          ? s.equipment.map((e) => (e.id === item.id ? { ...e, ...item } : e))
          : [...s.equipment, item]
      ),
      lastSuccessfulSyncAt: Date.now(),
      lastSyncAt: Date.now(),
    })),
}))

export function useSiteScopedEquipment() {
  const equipment = useOpsStore((s) => s.equipment)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  return equipment.filter((e) => e.siteId === selectedSiteId)
}

export function useSiteScopedZones() {
  const zones = useOpsStore((s) => s.zones)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  return zones.filter((z) => z.siteId === selectedSiteId)
}

export function useSiteScopedRoutes() {
  const routes = useOpsStore((s) => s.routes)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  return routes.filter((r) => r.siteId === selectedSiteId)
}

export function useSiteScopedOperators() {
  const operators = useOpsStore((s) => s.operators)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  return operators.filter((o) => o.siteId === selectedSiteId)
}

/** Load world from FastAPI when VITE_USE_API=true. Call once at app root. */
export async function bootstrapOpsFromApi() {
  if (!useApiMode) return
  try {
    const ctx = apiCtx(useOpsStore.getState())
    const payload = await fetchBootstrap({ lite: true, ctx })
    if (payload.error) throw new Error(payload.error)
    useOpsStore.getState().hydrateWorld(payload)
    try {
      const settings = await fetchOperationalSettings()
      useOpsStore.getState().applyOperationalSettings(settings)
    } catch {
      useOpsStore.setState({
        apiPollError: "Impossible de charger les paramètres opérationnels",
      })
    }
    void fetchBootstrap({ ctx })
      .then((full) => {
        if (!full.error) useOpsStore.getState().hydrateWorld(full)
      })
      .catch(() => {
        useOpsStore.setState({
          apiConnectionState: "degraded",
          apiPollError: "Synchronisation complète incomplète",
        })
      })
  } catch {
    useOpsStore.setState({ apiBootstrapped: true, apiPollError: "Backend indisponible", apiConnectionState: "offline" })
  }
}

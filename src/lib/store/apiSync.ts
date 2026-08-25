import { isValidProductionByShift } from "@/lib/production/mergeProduction"

export const SETTINGS_LOAD_ERROR = "Impossible de charger les paramètres opérationnels"
export const FULL_HYDRATE_ERROR = "Synchronisation complète incomplète"
export const POLL_INTERRUPT_ERROR = "Synchronisation interrompue"

const STICKY_MUTATION_ERRORS = new Set([
  "Échec enregistrement zone",
  "Échec suppression zone",
  "Échec mise à jour alerte",
])

export function isStickyMutationError(err: string | null | undefined): boolean {
  return err != null && STICKY_MUTATION_ERRORS.has(err)
}

/** Errors that equipment-only polls and lite hydrates must not clear. */
export function isStickyClientError(err: string | null | undefined): boolean {
  if (!err) return false
  return isStickyMutationError(err) || err === SETTINGS_LOAD_ERROR || err === FULL_HYDRATE_ERROR
}

export function isFullWorldPayload(payload: {
  productionByShift?: unknown
  timelineSegments?: unknown
}): boolean {
  return isValidProductionByShift(payload.productionByShift) && Array.isArray(payload.timelineSegments)
}

export function nextErrorAfterEquipmentPoll(current: string | null): string | null {
  return isStickyClientError(current) ? current : null
}

export function connectionAfterEquipmentPoll(opts: {
  fullWorldHydrated: boolean
  apiPollError: string | null
}): "online" | "degraded" {
  if (!opts.fullWorldHydrated) return "degraded"
  if (opts.apiPollError) return "degraded"
  return "online"
}

/** Stamp lastSuccessfulSyncAt only when the full world was loaded at least once. */
export function shouldStampSuccessfulSync(opts: {
  fullWorldHydrated: boolean
  apiPollError: string | null
}): boolean {
  return opts.fullWorldHydrated && opts.apiPollError !== FULL_HYDRATE_ERROR
}

export function nextErrorAfterFullHydrate(current: string | null): string | null {
  if (isStickyMutationError(current) || current === SETTINGS_LOAD_ERROR) return current
  return null
}

export function pollCatchError(current: string | null): string {
  return isStickyClientError(current) && current ? current : POLL_INTERRUPT_ERROR
}

export function withoutMatchingError(current: string | null, match: string | string[]): string | null {
  const matches = Array.isArray(match) ? match : [match]
  return current && matches.includes(current) ? null : current
}

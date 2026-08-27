export type AlertTimestamp = { occurredAt?: number | null; createdAt: number }

/** Operational event time, with a compatibility fallback for legacy/demo rows. */
export function operationalAlertTime(alert: AlertTimestamp): number {
  return alert.occurredAt ?? alert.createdAt
}

/** Copy and order alerts by their full operational timestamp, newest first. */
export function newestAlertsFirst<T extends AlertTimestamp>(alerts: readonly T[]): T[] {
  return [...alerts].sort(
    (left, right) => operationalAlertTime(right) - operationalAlertTime(left),
  )
}

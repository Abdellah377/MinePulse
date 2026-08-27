/** Copy and order operational alerts by their full timestamp, newest first. */
export function newestAlertsFirst<T extends { createdAt: number }>(alerts: readonly T[]): T[] {
  return [...alerts].sort((left, right) => right.createdAt - left.createdAt)
}

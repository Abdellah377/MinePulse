/** Shared in-flight dedupe and identity rules for Actions IA optimization POSTs. */

import { OPTIMIZATION_UNAVAILABLE_COPY } from "./actionsIaView"

const inflight = new Map<string, Promise<unknown>>()

export { OPTIMIZATION_UNAVAILABLE_COPY, OPTIMIZATION_UNAVAILABLE_DETAIL } from "./actionsIaView"

export function workflowRequestKey(alertId: string, investigationId?: string | null): string {
  return `${alertId}:${investigationId ?? "inv"}`
}

export function workflowIdentity(alertId: string | null | undefined, investigationId?: string | null): string | null {
  if (!alertId) return null
  return workflowRequestKey(alertId, investigationId)
}

export function shouldCancelWorkflowForIdentityChange(
  previous: { alertId: string | null; investigationId?: string | null },
  next: { alertId: string | null; investigationId?: string | null },
): boolean {
  return workflowIdentity(previous.alertId, previous.investigationId) !== workflowIdentity(next.alertId, next.investigationId)
}

/** Flipping optimizing must never abort the request that set it. */
export function shouldCancelWorkflowForOptimizingToggle(): boolean {
  return false
}

export function shouldApplyWorkflowResult(startedIdentity: string | null, currentIdentity: string | null): boolean {
  return Boolean(startedIdentity) && startedIdentity === currentIdentity
}

export function startSharedWorkflowRequest<T>(key: string, post: () => Promise<T>): Promise<T> {
  const existing = inflight.get(key) as Promise<T> | undefined
  if (existing) return existing
  const promise = post().finally(() => {
    if (inflight.get(key) === promise) inflight.delete(key)
  })
  inflight.set(key, promise)
  return promise
}

export function clearSharedWorkflowRequests(): void {
  inflight.clear()
}

export type SimulatedWorkflowRun = {
  outcome: string
  workflowStatus?: string | null
  candidates?: unknown[]
  displayedCandidateIds?: string[]
  baselineCandidateId?: string | null
  recommendedCandidateId?: string | null
  eligibility?: string
}

export type SimulatedWorkflowResult = {
  posts: number
  optimizing: boolean
  run: SimulatedWorkflowRun | null
  error: string | null
  failed: boolean
  showCalcul: boolean
  showRetry: boolean
}

/**
 * Models the auto-start effect, including a Strict Mode remount and an optimizing-flag rerender.
 * Cleanup must not drop the in-flight result for the same alert+investigation identity.
 */
export async function simulateOptimizationAutoStart(options: {
  alertId: string
  investigationId?: string | null
  shouldStart: boolean
  strictModeRemount?: boolean
  optimizingToggleRerunsEffect?: boolean
  post: () => Promise<SimulatedWorkflowRun>
}): Promise<SimulatedWorkflowResult> {
  let posts = 0
  let optimizing = false
  let run: SimulatedWorkflowRun | null = null
  let error: string | null = null
  let failed = false
  let autoKey: string | null = null
  const pending: Promise<unknown>[] = []
  const identity = workflowIdentity(options.alertId, options.investigationId)

  const attach = (startedIdentity: string) => {
    if (!options.shouldStart) return
    if (autoKey !== startedIdentity) autoKey = startedIdentity
    optimizing = true
    pending.push(
      startSharedWorkflowRequest(startedIdentity, () => {
        posts += 1
        return options.post()
      }).then((next) => {
        if (!shouldApplyWorkflowResult(startedIdentity, identity)) return
        run = next
        failed = false
        error = null
      }).catch(() => {
        if (!shouldApplyWorkflowResult(startedIdentity, identity)) return
        failed = true
        error = OPTIMIZATION_UNAVAILABLE_COPY
      }).finally(() => {
        if (shouldApplyWorkflowResult(startedIdentity, identity)) optimizing = false
      }),
    )
  }

  if (identity) attach(identity)
  if (options.optimizingToggleRerunsEffect && shouldCancelWorkflowForOptimizingToggle() && identity) {
    attach(identity)
  }
  if (options.strictModeRemount && identity) attach(identity)
  await Promise.all(pending)
  const showCalcul = optimizing && !run && !failed
  const showRetry = failed || Boolean(run)
  return { posts, optimizing, run, error, failed, showCalcul, showRetry }
}

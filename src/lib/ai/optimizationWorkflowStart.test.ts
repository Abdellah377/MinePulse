import { afterEach, describe, expect, it } from "vitest"
import { resolveActionsIaView, shouldStartOptimizationRun, actionsIaVisibility } from "./actionsIaView"
import {
  clearSharedWorkflowRequests,
  OPTIMIZATION_UNAVAILABLE_COPY,
  shouldApplyWorkflowResult,
  shouldCancelWorkflowForIdentityChange,
  shouldCancelWorkflowForOptimizingToggle,
  simulateOptimizationAutoStart,
  startSharedWorkflowRequest,
  workflowRequestKey,
} from "./optimizationWorkflowStart"

afterEach(() => clearSharedWorkflowRequests())

const readyEligible = {
  optimizationEligible: true,
  entryPhase: "ready" as const,
  resultStatus: "COMPLETED" as const,
  runOutcome: null as string | null,
}

describe("optimization run start contract", () => {
  it("successful investigation + optimizable alert is allowed to start one deterministic run", () => {
    expect(shouldStartOptimizationRun(readyEligible)).toBe(true)
    expect(workflowRequestKey("alert-1", "inv-9")).toBe("alert-1:inv-9")
  })

  it("does not cancel an in-flight workflow when optimizing flips true", () => {
    expect(shouldCancelWorkflowForOptimizingToggle()).toBe(false)
  })

  it("strict-mode remount and optimizing rerender still apply the result and clear optimizing", async () => {
    const result = await simulateOptimizationAutoStart({
      alertId: "alert-1",
      investigationId: "inv-1",
      shouldStart: true,
      strictModeRemount: true,
      optimizingToggleRerunsEffect: true,
      post: async () => ({ outcome: "FEASIBLE", eligibility: "OPTIMIZABLE" }),
    })
    expect(result.posts).toBe(1)
    expect(result.optimizing).toBe(false)
    expect(result.run?.outcome).toBe("FEASIBLE")
    expect(result.showCalcul).toBe(false)
    expect(result.failed).toBe(false)
  })

  it("run success stores the returned run and leaves the processing state", async () => {
    const result = await simulateOptimizationAutoStart({
      alertId: "alert-1",
      shouldStart: true,
      post: async () => ({ outcome: "FEASIBLE", workflowStatus: "ORCHESTRATED" }),
    })
    expect(result.run).toEqual({ outcome: "FEASIBLE", workflowStatus: "ORCHESTRATED" })
    expect(result.optimizing).toBe(false)
    expect(resolveActionsIaView({ ...readyEligible, runOutcome: result.run?.outcome, optimizing: result.optimizing })).toBe("complete_feasible")
  })

  it.each([
    ["FEASIBLE", "complete_feasible"],
    ["NO_CHANGE", "complete_no_change"],
    ["INSUFFICIENT_DATA", "complete_insufficient"],
    ["NO_FEASIBLE_PLAN", "complete_no_feasible"],
  ] as const)("%s moves UI out of Calcul", (outcome, state) => {
    const input = {
      ...readyEligible,
      runOutcome: outcome === "NO_CHANGE" ? "FEASIBLE" : outcome,
      workflowStatus: outcome === "NO_CHANGE" ? "NO_CHANGE_RECOMMENDED" : null,
      optimizing: false,
    }
    expect(resolveActionsIaView(input)).toBe(state)
    expect(actionsIaVisibility(state).showDispatchOptions).toBe(true)
    expect(state).not.toBe("optimizing")
  })

  it("frontend timeout clears optimizing and shows retry", async () => {
    const result = await simulateOptimizationAutoStart({
      alertId: "alert-1",
      shouldStart: true,
      post: async () => {
        throw new Error("timeout")
      },
    })
    expect(result.optimizing).toBe(false)
    expect(result.failed).toBe(true)
    expect(result.error).toBe(OPTIMIZATION_UNAVAILABLE_COPY)
    expect(result.showRetry).toBe(true)
    expect(result.showCalcul).toBe(false)
    expect(resolveActionsIaView({ ...readyEligible, optimizationFailed: true, optimizing: false })).toBe("optimization_failed")
    expect(actionsIaVisibility("optimization_failed").showRetry).toBe(true)
  })

  it("failed auto-start does not loop; manual retry can POST again", async () => {
    const first = await simulateOptimizationAutoStart({
      alertId: "alert-1",
      investigationId: "inv-1",
      shouldStart: true,
      post: async () => {
        throw new Error("down")
      },
    })
    expect(shouldStartOptimizationRun({ ...readyEligible, optimizationFailed: true })).toBe(false)
    clearSharedWorkflowRequests()
    const retry = await startSharedWorkflowRequest("alert-1:inv-1", async () => ({ outcome: "FEASIBLE" }))
    expect(first.posts).toBe(1)
    expect(retry.outcome).toBe("FEASIBLE")
  })

  it("inbox refresh / same identity does not count as a cancel", () => {
    expect(
      shouldCancelWorkflowForIdentityChange(
        { alertId: "a", investigationId: "i" },
        { alertId: "a", investigationId: "i" },
      ),
    ).toBe(false)
  })

  it("stale response from a previously selected alert is ignored", () => {
    expect(shouldApplyWorkflowResult("alert-old:inv", "alert-new:inv")).toBe(false)
    expect(shouldApplyWorkflowResult("alert-new:inv", "alert-new:inv")).toBe(true)
  })

  it("reusable run and non-eligible or uninvestigated alerts do not start a run", () => {
    expect(shouldStartOptimizationRun({ ...readyEligible, runOutcome: "FEASIBLE" })).toBe(false)
    expect(shouldStartOptimizationRun({ ...readyEligible, optimizationEligible: false })).toBe(false)
    expect(shouldStartOptimizationRun({ optimizationEligible: true, entryPhase: "absent" })).toBe(false)
    expect(shouldStartOptimizationRun({ ...readyEligible, hasDispatchSubject: false })).toBe(false)
  })
})

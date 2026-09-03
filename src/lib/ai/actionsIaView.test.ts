import { describe, expect, it } from "vitest"

import {
  FMS_DECISION_NOTE,
  INVESTIGATION_REQUIRED_COPY,
  actionsIaVisibility,
  hasReusableOptimizationRun,
  isSuccessfulInvestigation,
  resolveActionsIaView,
  shouldStartOptimizationWorkflow,
} from "./actionsIaView"

const hiddenUntilInvestigation = {
  showAction: false,
  showOptimization: false,
  showImpact: false,
  showDispatchOptions: false,
  showDecisionControls: false,
  showTechnicalDetails: false,
}

describe("actionsIaView investigation-first gating", () => {
  it("STATE A: selecting a dossier does not count as investigated", () => {
    const state = resolveActionsIaView({
      optimizationEligible: true,
      hasInvestigation: false,
      entryPhase: "absent",
    })
    expect(state).toBe("not_investigated")
    expect(isSuccessfulInvestigation("absent", null)).toBe(false)
    expect(shouldStartOptimizationWorkflow({ optimizationEligible: true, entryPhase: "absent" })).toBe(false)
    expect(actionsIaVisibility(state)).toMatchObject({
      showInvestiguer: true,
      showInvestigationProgress: false,
      ...hiddenUntilInvestigation,
    })
  })

  it("treats an inbox investigation flag without a loaded result as in-flight, not complete", () => {
    expect(
      resolveActionsIaView({
        optimizationEligible: true,
        hasInvestigation: true,
        entryPhase: undefined,
      }),
    ).toBe("investigating")
  })

  it("STATE B: loading or running hides recommendations and optimization", () => {
    for (const entryPhase of ["loading", "running"] as const) {
      const state = resolveActionsIaView({ optimizationEligible: true, entryPhase, resultStatus: "PENDING" })
      expect(state).toBe("investigating")
      expect(shouldStartOptimizationWorkflow({ optimizationEligible: true, entryPhase, resultStatus: "PENDING" })).toBe(false)
      expect(actionsIaVisibility(state)).toMatchObject({
        showInvestiguer: false,
        showInvestigationProgress: true,
        ...hiddenUntilInvestigation,
      })
    }
  })

  it("STATE C: failure keeps optimization hidden and offers retry", () => {
    const state = resolveActionsIaView({ optimizationEligible: true, entryPhase: "error", resultStatus: "FAILED" })
    expect(state).toBe("investigation_failed")
    expect(shouldStartOptimizationWorkflow({ optimizationEligible: true, entryPhase: "error", resultStatus: "FAILED" })).toBe(false)
    expect(actionsIaVisibility(state)).toMatchObject({
      showInvestiguer: true,
      showInvestigationProgress: false,
      ...hiddenUntilInvestigation,
    })
  })

  it("STATE D: successful investigation that is not optimizable never starts a workflow", () => {
    const input = {
      optimizationEligible: false,
      entryPhase: "ready" as const,
      resultStatus: "COMPLETED_WITH_UNCERTAINTY",
    }
    expect(isSuccessfulInvestigation(input.entryPhase, input.resultStatus)).toBe(true)
    expect(shouldStartOptimizationWorkflow(input)).toBe(false)
    const state = resolveActionsIaView(input)
    expect(state).toBe("complete_not_optimizable")
    expect(actionsIaVisibility(state)).toMatchObject({
      showInvestiguer: false,
      showAction: true,
      showOptimization: false,
      showDispatchOptions: false,
      showDecisionControls: true,
      showImpact: false,
    })
  })

  it("STATE E: success + eligible + no reusable run starts the workflow once", () => {
    const input = {
      optimizationEligible: true,
      entryPhase: "ready" as const,
      resultStatus: "COMPLETED",
      runOutcome: null,
    }
    expect(shouldStartOptimizationWorkflow(input)).toBe(true)
    expect(resolveActionsIaView(input)).toBe("optimizing")
    expect(shouldStartOptimizationWorkflow({ ...input, optimizing: true })).toBe(false)
    expect(actionsIaVisibility("optimizing")).toMatchObject({
      showAction: false,
      showOptimization: true,
      showDispatchOptions: true,
      showDecisionControls: false,
      showTechnicalDetails: false,
    })
  })

  it("does not re-POST when a reusable run already exists", () => {
    expect(hasReusableOptimizationRun("FEASIBLE")).toBe(true)
    expect(hasReusableOptimizationRun("NO_FEASIBLE_PLAN")).toBe(true)
    expect(hasReusableOptimizationRun("INSUFFICIENT_DATA")).toBe(true)
    expect(hasReusableOptimizationRun("ERROR")).toBe(false)
    expect(hasReusableOptimizationRun(null)).toBe(false)
    expect(
      shouldStartOptimizationWorkflow({
        optimizationEligible: true,
        entryPhase: "ready",
        resultStatus: "COMPLETED",
        runOutcome: "FEASIBLE",
      }),
    ).toBe(false)
  })

  it("STATE F / G: maps feasible, no-change, no-feasible, and insufficient outcomes", () => {
    const base = { optimizationEligible: true, entryPhase: "ready" as const, resultStatus: "COMPLETED" }
    expect(resolveActionsIaView({ ...base, runOutcome: "FEASIBLE" })).toBe("complete_feasible")
    expect(resolveActionsIaView({ ...base, runOutcome: "FEASIBLE", workflowStatus: "NO_CHANGE_RECOMMENDED" })).toBe("complete_no_change")
    expect(resolveActionsIaView({ ...base, runOutcome: "NO_FEASIBLE_PLAN" })).toBe("complete_no_feasible")
    expect(resolveActionsIaView({ ...base, runOutcome: "INSUFFICIENT_DATA" })).toBe("complete_insufficient")
    expect(actionsIaVisibility("complete_feasible")).toMatchObject({
      showAction: true,
      showOptimization: true,
      showImpact: true,
      showDispatchOptions: true,
      showDecisionControls: true,
      showTechnicalDetails: true,
    })
  })

  it("keeps the investigation-required copy and a single FMS decision note", () => {
    expect(INVESTIGATION_REQUIRED_COPY).toContain("avant d’afficher les recommandations")
    expect(INVESTIGATION_REQUIRED_COPY).not.toContain("n’est pas requise")
    expect(FMS_DECISION_NOTE).toContain("Aucune commande opérationnelle n’est exécutée automatiquement")
  })
})

import { describe, expect, it } from "vitest"

import {
  canonicalHomeTitle,
  contextDedupeKey,
  hasContextualIdentity,
  isModuleHomeContext,
  isModuleHomeTab,
  moduleHomeDedupeKey,
  prepareWorkspaceContext,
} from "@/lib/workspace/titles"
import { MODULE_HOME } from "@/lib/workspace/types"

describe("module home identity", () => {
  it("uses a stable home key for each top-level type", () => {
    expect(moduleHomeDedupeKey("alerts")).toBe("alerts|home")
    expect(moduleHomeDedupeKey("actions")).toBe("actions|home")
    expect(moduleHomeDedupeKey("map")).toBe("map|home")
    expect(moduleHomeDedupeKey("timeline")).toBe("timeline|home")
    expect(moduleHomeDedupeKey("performance")).toBe("performance|home")
    expect(moduleHomeDedupeKey("settings")).toBe("settings|home")
    expect(moduleHomeDedupeKey("oem")).toBe("oem|connectivity")
  })

  it("does not treat performance metric or alert selection as a new home key", () => {
    expect(contextDedupeKey("performance", MODULE_HOME.performance.context)).toBe("performance|home")
    expect(contextDedupeKey("performance", {})).toBe("performance|home")
    expect(contextDedupeKey("alerts", { _home: true, alertId: "alert-1" })).toBe("alerts|home")
    expect(contextDedupeKey("alerts", { _home: true, investigationId: "inv-1" })).toBe("alerts|home")
  })

  it("keeps contextual workspaces distinct from home", () => {
    expect(hasContextualIdentity("actions", { equipmentCode: "TRK-009" })).toBe(true)
    expect(contextDedupeKey("actions", { equipmentId: "e9", equipmentCode: "TRK-009" })).toBe("actions|eq:e9")
    expect(contextDedupeKey("actions", { equipmentId: "e15", equipmentCode: "TRK-015" })).toBe("actions|eq:e15")
    expect(contextDedupeKey("map", { equipmentId: "e9", equipmentCode: "TRK-009" })).toBe("map|eq:e9")
    expect(isModuleHomeContext("actions", { equipmentCode: "TRK-009" })).toBe(false)
  })

  it("strips a home stamp when opening a contextual workspace", () => {
    const prepared = prepareWorkspaceContext("actions", {
      _home: true,
      alertId: "alert-1",
      investigationId: "inv-1",
      equipmentCode: "TRK-009",
    })
    expect(prepared._home).toBeUndefined()
    expect(contextDedupeKey("actions", prepared)).toContain("alert:alert-1")
  })

  it("recognizes mutated homes that kept the canonical title", () => {
    expect(
      isModuleHomeTab({
        type: "alerts",
        title: canonicalHomeTitle("alerts"),
        context: { alertId: "alert-1" },
      }),
    ).toBe(true)
    expect(
      isModuleHomeTab({
        type: "actions",
        title: "Actions IA — TRK-009",
        context: { equipmentCode: "TRK-009" },
      }),
    ).toBe(false)
  })
})

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"
import AlertesIA from "@/pages/AlertesIA"
import ActionsIA from "@/pages/ActionsIA"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { buildCurrentIntelligence } from "@/lib/ai/alertIntelligence"
vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), useApiMode: false }))
vi.mock("@/components/ai/InvestigationAlerts", () => ({ InvestigationAlerts: () => { throw new Error("Live AI in demo mode") } }))
vi.mock("@/components/ai/InvestigationActions", () => ({ InvestigationActions: () => { throw new Error("Live actions in demo mode") } }))
it("demo mode still creates and renders its intentional scenario data without an API", () => {
  const world = useOpsStore.getInitialState()
  expect(world.equipment.length).toBeGreaterThan(0)
  expect(buildCurrentIntelligence(world.alerts, world.equipment, world.zones).length).toBeGreaterThan(0)
  expect(renderToStaticMarkup(createElement(AlertesIA))).toContain("Confiance")
  expect(renderToStaticMarkup(createElement(ActionsIA))).toContain("Actions")
})

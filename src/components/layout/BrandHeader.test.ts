import { readFileSync } from "node:fs"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { expect, it } from "vitest"

import { BrandHeader } from "@/components/layout/BrandHeader"
import { useAlertFeedStore } from "@/lib/store/useAlertFeedStore"

it("does not map the alert feed inside the Zustand selector", () => {
  const source = readFileSync("src/components/layout/BrandHeader.tsx", "utf8")
  expect(source).not.toMatch(/useAlertFeedStore\(\(s\) => s\.orderedIds\.map/)
  expect(source).toContain("useVisibleAlerts")
})

it("BrandHeader renders with a populated alert feed without throwing", () => {
  useAlertFeedStore.setState({
    orderedIds: ["a1"],
    byId: {
      a1: {
        id: "a1",
        title: "A",
        description: "",
        severity: "warning",
        status: "new",
        category: "X",
        source: "RULE",
        createdAt: 1,
        updatedAt: 1,
        assignedTo: null,
        resolution: null,
        equipmentId: null,
        zoneId: null,
        location: "",
      },
    },
  })
  expect(() =>
    renderToStaticMarkup(
      createElement(MemoryRouter, { initialEntries: ["/alertes"] }, createElement(BrandHeader)),
    ),
  ).not.toThrow()
})

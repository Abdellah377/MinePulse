import { createElement } from "react"
import { readFileSync } from "node:fs"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"
import { AlertToastStack } from "./AlertToasts"
import type { AlertNotice } from "@/lib/alerts/notifications"

const current: AlertNotice = {
  id: "alert-1",
  alertId: "alert-1",
  title: "TRK-002 — Attente prolongée",
  description: "File d’attente inhabituelle.",
  severity: "critical",
  kind: "current",
}

const prediction: AlertNotice = {
  id: "alert-pred",
  alertId: "alert-pred",
  title: "TRK-010 — Risque mécanique prédit élevé",
  description: "Risque mécanique prédit élevé dans les 60 prochaines minutes.",
  severity: "warning",
  kind: "prediction",
}

it("renders compact top-right toasts without demo copy or certainty of failure", () => {
  const html = renderToStaticMarkup(
    createElement(AlertToastStack, { notices: [prediction, current], onOpen: () => undefined, onDismiss: () => undefined }),
  )
  expect(html).toContain("fixed")
  expect(html).toContain("right-")
  expect(html).toContain("top-")
  expect(html).toContain(current.title)
  expect(html).toContain(prediction.title)
  expect(html).toContain("Prédiction")
  expect(html).not.toContain("Le camion va tomber en panne")
  expect(html).not.toContain("buildPredictionIntelligence")
})

it("API mode never imports demo prediction intelligence for toasts", () => {
  const source = readFileSync("src/components/alerts/AlertToasts.tsx", "utf8")
  expect(source).not.toContain("buildPredictionIntelligence")
  expect(source).not.toContain("alertIntelligence")
  expect(source).toContain("diffNewAlerts")
  expect(source).toContain("alertWorkspaceContext")
  expect(readFileSync("src/components/layout/AppShell.tsx", "utf8")).toContain("AlertToasts")
})

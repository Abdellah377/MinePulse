import { useEffect } from "react"

import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"

export function useWorkspaceKeyboard() {
  const nextTab = useWorkspaceStore((s) => s.nextTab)
  const prevTab = useWorkspaceStore((s) => s.prevTab)
  const closeTab = useWorkspaceStore((s) => s.closeTab)
  const activateByIndex = useWorkspaceStore((s) => s.activateByIndex)
  const activeTabId = useWorkspaceStore((s) => s.activeTabId)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.ctrlKey || e.metaKey
      if (meta && e.key === "Tab") {
        e.preventDefault()
        if (e.shiftKey) prevTab()
        else nextTab()
        return
      }
      if (meta && (e.key === "w" || e.key === "W")) {
        // Avoid closing browser tab when possible
        if (activeTabId) {
          e.preventDefault()
          closeTab(activeTabId)
        }
        return
      }
      if (e.altKey && e.key >= "1" && e.key <= "9") {
        e.preventDefault()
        activateByIndex(Number(e.key) - 1)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [nextTab, prevTab, closeTab, activateByIndex, activeTabId])
}

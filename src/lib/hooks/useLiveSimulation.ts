import { useEffect } from "react"

import { fetchBootstrap, fetchEquipmentLive, useApiMode } from "@/lib/api/client"
import { pollCatchError } from "@/lib/store/apiSync"
import { useOpsStore } from "@/lib/store/useOpsStore"

/** Poll backend when API mode; otherwise client-side mock tick. */
export function useLiveSimulation(intervalMs = 2200) {
  const tick = useOpsStore((s) => s.tick)
  const hydrateFromApi = useOpsStore((s) => s.hydrateFromApi)
  const hydrateWorld = useOpsStore((s) => s.hydrateWorld)
  const apiBootstrapped = useOpsStore((s) => s.apiBootstrapped)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)

  useEffect(() => {
    if (useApiMode) {
      if (!apiBootstrapped) return

      let cancelled = false
      let n = 0
      const ctx = { siteCode: selectedSiteId, shiftId: selectedShiftId }
      const poll = async () => {
        while (!cancelled) {
          try {
            if (n % 5 === 0) {
              const payload = await fetchBootstrap({ ctx })
              if (!payload.error) hydrateWorld(payload)
            } else {
              const equipment = await fetchEquipmentLive(ctx)
              hydrateFromApi({ equipment })
            }
            n += 1
          } catch {
            const current = useOpsStore.getState().apiPollError
            useOpsStore.setState({
              apiPollError: pollCatchError(current),
              apiConnectionState: "degraded",
            })
          }
          await new Promise((r) => setTimeout(r, intervalMs))
        }
      }
      void poll()
      return () => {
        cancelled = true
      }
    }

    const id = window.setInterval(() => {
      tick()
    }, intervalMs)
    return () => window.clearInterval(id)
  }, [
    tick,
    hydrateFromApi,
    hydrateWorld,
    intervalMs,
    apiBootstrapped,
    selectedSiteId,
    selectedShiftId,
  ])
}

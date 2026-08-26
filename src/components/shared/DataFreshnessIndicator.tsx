import { useEffect, useState } from "react"
import { Circle } from "lucide-react"

import { useApiMode } from "@/lib/api/client"
import { cn } from "@/lib/utils"
import { timeAgo } from "@/lib/format"
import { useOpsStore } from "@/lib/store/useOpsStore"

const LIVE_THRESHOLD_MS = 30_000

export function DataFreshnessIndicator({
  className,
  muted = false,
}: {
  className?: string
  /** Soften contrast (e.g. in BrandHeader). */
  muted?: boolean
}) {
  const lastSuccessfulSyncAt = useOpsStore((s) => s.lastSuccessfulSyncAt)
  const apiPollError = useOpsStore((s) => s.apiPollError)
  const apiConnectionState = useOpsStore((s) => s.apiConnectionState)
  const fullWorldHydrated = useOpsStore((s) => s.fullWorldHydrated)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const syncAt = lastSuccessfulSyncAt
  const live =
    useApiMode &&
    fullWorldHydrated &&
    apiConnectionState === "online" &&
    !apiPollError &&
    lastSuccessfulSyncAt != null &&
    now - lastSuccessfulSyncAt < LIVE_THRESHOLD_MS

  const label =
    !useApiMode ? "DÉMO" : apiPollError != null
      ? "HORS LIGNE"
      : live
        ? "API SYNCHRONISÉE"
        : syncAt != null
          ? timeAgo(syncAt, now)
          : "—"

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 text-[10px] font-semibold tracking-wide",
        muted ? "text-white/90" : "text-muted",
        className
      )}
      title={apiPollError ?? (syncAt != null ? `Dernière synchro API ${timeAgo(syncAt, now)} — ne garantit pas la fraîcheur des capteurs` : "Aucune synchro")}
    >
      <Circle
        className={cn(
          "size-1.5 fill-current",
          apiPollError
            ? muted
              ? "text-red-300"
              : "text-destructive"
            : live
              ? muted
                ? "text-emerald-300"
                : "text-success"
              : muted
                ? "text-amber-300"
                : "text-warning"
        )}
        style={{ animation: live ? "pulse-dot 2s infinite" : undefined }}
      />
      {label}
    </div>
  )
}

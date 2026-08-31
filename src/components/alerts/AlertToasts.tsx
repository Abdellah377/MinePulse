import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"

import { useOpsStore } from "@/lib/store/useOpsStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import { SEVERITY_CONFIG } from "@/lib/status"
import { cn } from "@/lib/utils"
import {
  alertWorkspaceContext,
  diffNewAlerts,
  toAlertNotice,
  type AlertNotice,
} from "@/lib/alerts/notifications"

const MAX_TOASTS = 4
const DISMISS_MS = 8_000

export function AlertToasts() {
  const alerts = useOpsStore((s) => s.alerts)
  const equipment = useOpsStore((s) => s.equipment)
  const apiBootstrapped = useOpsStore((s) => s.apiBootstrapped)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const navigate = useNavigate()
  const seen = useRef<Set<string> | null>(null)
  const [notices, setNotices] = useState<AlertNotice[]>([])

  useEffect(() => {
    const codes = new Map(equipment.map((item) => [item.id, item.code]))
    const { seen: next, fresh } = diffNewAlerts(seen.current, alerts, apiBootstrapped)
    seen.current = next
    if (!fresh.length) return
    const incoming = fresh.map((alert) =>
      toAlertNotice(alert, alert.equipmentId ? codes.get(alert.equipmentId) : null),
    )
    setNotices((current) => [...incoming, ...current].slice(0, MAX_TOASTS))
  }, [alerts, equipment, apiBootstrapped])

  useEffect(() => {
    if (!notices.length) return
    const timer = window.setTimeout(() => {
      setNotices((current) => current.slice(0, -1))
    }, DISMISS_MS)
    return () => window.clearTimeout(timer)
  }, [notices])

  function openAlert(alertId: string) {
    const alert = alerts.find((row) => row.id === alertId)
    if (!alert) return
    const code = alert.equipmentId
      ? equipment.find((item) => item.id === alert.equipmentId)?.code
      : undefined
    openWorkspace({
      type: "alerts",
      context: alertWorkspaceContext(alert, code),
      title: alert.title,
    })
    navigate("/alertes")
    setNotices((current) => current.filter((notice) => notice.alertId !== alertId))
  }

  return (
    <AlertToastStack
      notices={notices}
      onOpen={openAlert}
      onDismiss={(id) => setNotices((current) => current.filter((notice) => notice.id !== id))}
    />
  )
}

export function AlertToastStack({
  notices,
  onOpen,
  onDismiss,
}: {
  notices: AlertNotice[]
  onOpen: (alertId: string) => void
  onDismiss: (id: string) => void
}) {
  if (!notices.length) return null
  return (
    <div
      className="pointer-events-none fixed right-3 top-14 z-50 flex w-[min(100%-1.5rem,22rem)] flex-col gap-2"
      aria-live="polite"
    >
      {notices.map((notice) => {
        const cfg = SEVERITY_CONFIG[notice.severity]
        return (
          <div
            key={notice.id}
            className={cn(
              "pointer-events-auto relative rounded-md border bg-surface px-3 py-2.5 shadow-lg",
              cfg.border,
              notice.severity === "critical" ? "ring-1 ring-severity-critical/40" : "",
            )}
          >
            <button
              type="button"
              className="w-full pr-12 text-left"
              onClick={() => onOpen(notice.alertId)}
            >
              <div className="flex items-center gap-1.5">
                <span className={cn("size-1.5 shrink-0 rounded-full", cfg.dot)} />
                <span className={cn("text-[10px] font-semibold uppercase tracking-wide", cfg.color)}>
                  {notice.kind === "prediction" ? "Prédiction" : cfg.label}
                </span>
              </div>
              <p className="mt-1 text-[12px] font-medium text-foreground">{notice.title}</p>
              <p className="line-clamp-2 text-[11px] text-muted">{notice.description}</p>
            </button>
            <button
              type="button"
              className="absolute right-2 top-2 text-[11px] text-muted-2 hover:text-foreground"
              onClick={() => onDismiss(notice.id)}
            >
              Fermer
            </button>
          </div>
        )
      })}
    </div>
  )
}

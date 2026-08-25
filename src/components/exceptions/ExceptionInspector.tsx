import {
  Map as MapIcon,
  Film as FilmIcon,
  UserPlus,
  Check,
  Search,
  Sparkles,
  Truck,
} from "lucide-react"

import type { ReactNode } from "react"

import type { Alert } from "@/lib/mock/types"
import { ALERT_STATUS_LABEL } from "@/lib/mock/types"
import { SEVERITY_CONFIG, STATE_CONFIG } from "@/lib/status"
import { formatShortTime, timeAgo } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { useUiStore } from "@/lib/store/useUiStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import {
  CAUSE_KIND_LABEL,
  investigateException,
} from "@/lib/ai/exceptionInvestigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MiniTimelineStrip } from "@/components/equipment/MiniTimelineStrip"

export function ExceptionInspector({ alert }: { alert: Alert }) {
  const equipment = useOpsStore((s) => s.equipment)
  const zones = useOpsStore((s) => s.zones)
  const timelineSegments = useOpsStore((s) => s.timelineSegments)
  const simNowIso = useOpsStore((s) => s.simNowIso)
  const updateAlertStatus = useOpsStore((s) => s.updateAlertStatus)
  const openEquipmentDrawer = useUiStore((s) => s.openEquipmentDrawer)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)

  const cfg = SEVERITY_CONFIG[alert.severity]
  const eq = equipment.find((e) => e.id === alert.equipmentId)
  const zone = zones.find((z) => z.id === alert.zoneId)
  const eqCfg = eq ? STATE_CONFIG[eq.state] : null
  const inv = investigateException(alert, eq?.code)
  const invId = `inv-${alert.id}`

  const segs = timelineSegments
    .filter((s) => s.equipmentId === alert.equipmentId)
    .sort((a, b) => a.start - b.start)
    .slice(-12)
  const rangeStart = segs[0]?.start ?? (simNowIso ? new Date(simNowIso).getTime() - 3_600_000 : Date.now() - 3_600_000)
  const rangeEnd = simNowIso ? new Date(simNowIso).getTime() : Date.now()

  const nearby = zone
    ? equipment.filter((e) => e.zoneId === zone.id).slice(0, 6)
    : []

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <Badge className={cn(cfg.bg, cfg.color, "border-transparent")}>{cfg.label}</Badge>
          <Badge variant="outline">{alert.category}</Badge>
          <Badge variant="outline">{ALERT_STATUS_LABEL[alert.status]}</Badge>
        </div>
        <h3 className="text-[14px] font-semibold text-foreground">{alert.title}</h3>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {/* A. Résumé */}
        <Section title="Résumé">
          <p className="text-[12px] leading-relaxed text-muted">{alert.description}</p>
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
            <Fact label="Où" value={alert.location} />
            <Fact label="Durée" value={timeAgo(alert.createdAt)} />
            <Fact label="Depuis" value={formatShortTime(alert.createdAt)} />
            <Fact label="Statut" value={ALERT_STATUS_LABEL[alert.status]} />
            <Fact label="Équipement" value={eq?.code ?? "—"} mono />
            <Fact label="Impact" value={inv.impact} />
          </dl>
        </Section>

        {/* B. Evidence */}
        <Section title="Preuves">
          {eq && eqCfg && (
            <p className={cn("mb-2 flex items-center gap-1.5 text-[11px]", eqCfg.color)}>
              <span className={cn("size-1.5 rounded-full", eqCfg.dot)} />
              État actuel : {eqCfg.label}
            </p>
          )}
          {segs.length > 0 && (
            <div className="mb-2">
              <p className="mb-1 text-[10px] font-semibold uppercase text-muted-2">Film récent</p>
              <MiniTimelineStrip segments={segs} rangeStart={rangeStart} rangeEnd={rangeEnd} />
            </div>
          )}
          {nearby.length > 0 && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase text-muted-2">Engins proches</p>
              <div className="flex flex-wrap gap-1">
                {nearby.map((e) => (
                  <Badge key={e.id} variant="outline" className="font-mono text-[10px]">
                    {e.code}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {alert.resolution && (
            <p className="mt-2 rounded-md border border-success/25 bg-success/10 px-2 py-1.5 text-[11px] text-success">
              Cause / résolution : {alert.resolution}
            </p>
          )}
        </Section>

        {/* C. AI Investigation */}
        <Section title="Investigation IA">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="text-[10px]">
              {CAUSE_KIND_LABEL[inv.causeKind]}
            </Badge>
            <span className="text-[10px] text-muted-2">Confiance {inv.confidence} %</span>
          </div>
          <p className="text-[12px] font-medium text-foreground">{inv.probableCause}</p>
          <Block title="Faits confirmés" items={inv.facts} />
          <Block title="Éléments favorables" items={inv.supporting} />
          {inv.contradictory.length > 0 && (
            <Block title="Éléments contradictoires" items={inv.contradictory} />
          )}
          <Block title="Informations manquantes" items={inv.missing} />
          <p className="mt-2 text-[11px] text-muted">
            <span className="font-semibold text-foreground/80">Vérification : </span>
            {inv.verification}
          </p>
          <p className="mt-1 text-[11px] text-muted">
            <span className="font-semibold text-foreground/80">Si ignoré : </span>
            {inv.ifIgnored}
          </p>
        </Section>

        {/* D. Actions */}
        <Section title="Actions">
          {alert.status !== "resolved" && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              <Button size="sm" variant="outline" onClick={() => updateAlertStatus(alert.id, "acknowledged")}>
                Acquitter
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => updateAlertStatus(alert.id, "investigating", "Régulateur de poste")}
              >
                <Search className="size-3.5" />
                En investigation
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => updateAlertStatus(alert.id, "assigned", "Régulateur de poste")}
              >
                <UserPlus className="size-3.5" />
                Assigner
              </Button>
              <Button size="sm" onClick={() => updateAlertStatus(alert.id, "resolved")}>
                <Check className="size-3.5" />
                Résoudre
              </Button>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Button
              size="sm"
              variant="outline"
              className="justify-start"
              onClick={() =>
                openWorkspace({
                  type: "map",
                  investigationId: invId,
                  context: {
                    equipmentId: eq?.id,
                    equipmentCode: eq?.code,
                    zoneId: zone?.id,
                    zoneName: zone?.name,
                    alertId: alert.id,
                    investigationId: invId,
                  },
                })
              }
            >
              <MapIcon className="size-3.5" />
              Voir sur la Carte
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="justify-start"
              disabled={!eq}
              onClick={() =>
                eq &&
                openWorkspace({
                  type: "timeline",
                  investigationId: invId,
                  context: {
                    equipmentId: eq.id,
                    equipmentCode: eq.code,
                    alertId: alert.id,
                    investigationId: invId,
                  },
                })
              }
            >
              <FilmIcon className="size-3.5" />
              Ouvrir le Film
            </Button>
            {eq && (
              <Button size="sm" variant="outline" className="justify-start" onClick={() => openEquipmentDrawer(eq.id)}>
                <Truck className="size-3.5" />
                Ouvrir l&apos;équipement
              </Button>
            )}
            <Button
              size="sm"
              className="justify-start"
              onClick={() =>
                openWorkspace({
                  type: "actions",
                  investigationId: invId,
                  context: {
                    zoneName: zone?.name ?? "Banc B",
                    zoneId: zone?.id,
                    alertId: alert.id,
                    investigationId: invId,
                    equipmentId: eq?.id,
                    equipmentCode: eq?.code,
                  },
                })
              }
            >
              <Sparkles className="size-3.5" />
              Générer des solutions IA
            </Button>
          </div>
        </Section>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-2">{title}</h4>
      <div className="rounded-md border border-border bg-surface-2/30 p-3">{children}</div>
    </section>
  )
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-muted-2">{label}</dt>
      <dd className={cn("text-foreground/90", mono && "font-mono font-medium")}>{value}</dd>
    </div>
  )
}

function Block({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div className="mt-2">
      <p className="text-[10px] font-semibold text-muted-2">{title}</p>
      <ul className="mt-0.5 list-inside list-disc text-[11px] text-muted">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </div>
  )
}

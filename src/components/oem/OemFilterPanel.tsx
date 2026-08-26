import type { ReactNode } from "react"
import { ChevronLeft, ChevronRight, Search } from "lucide-react"
import { useEffect, useState } from "react"

import { oemApi, type OemCatalog } from "@/lib/api/oem"
import { dateFromIso } from "@/lib/oem/format"
import type { OemCol, OemDraft } from "@/lib/oem/types"
import { OEM_TYPE_GROUP, UNAVAILABLE_SIM } from "@/lib/oem/types"
import type { OemView } from "@/lib/workspace/types"
import { useOpsStore, useSiteScopedEquipment } from "@/lib/store/useOpsStore"
import { OemEquipmentTree } from "@/components/oem/OemEquipmentTree"
import { OemParameterSelector } from "@/components/oem/OemParameterSelector"
import { OemExportButton } from "@/components/oem/OemExportButton"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const PANEL_WIDTH = 240
const CTL = "h-7 w-full rounded-xl text-xs"

export function OemFilterPanel({
  view,
  internalTab,
  draft,
  onChange,
  onApply,
  exportRows,
  exportCols,
  exportContext,
  exportName,
}: {
  view: OemView
  internalTab?: string
  draft: OemDraft
  onChange: (next: OemDraft) => void
  onApply: () => void
  exportRows?: Record<string, unknown>[]
  exportCols?: OemCol[]
  exportContext?: Record<string, string>
  exportName?: string
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [catalog, setCatalog] = useState<OemCatalog | null>(null)
  const tyrePositions = catalog?.tyrePositions ?? []
  const equipment = useSiteScopedEquipment()
  const sites = useOpsStore((s) => s.sites)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const shifts = useOpsStore((s) => s.shifts)
  const simNowIso = useOpsStore((s) => s.simNowIso)
  const siteName = sites.find((s) => s.id === selectedSiteId)?.name ?? selectedSiteId
  const types = Array.from(new Set(equipment.map((e) => e.type)))
  const showParams =
    view === "multi" ||
    (view === "diagnostic" && (internalTab === "parametres" || internalTab === "analyse")) ||
    (view === "maintenance" && internalTab === "indicateurs")
  const showTyres = view === "pneus"
  const showDelay = view === "connectivite"
  const showErrorFilters =
    (view === "diagnostic" && internalTab === "erreurs") || (view === "maintenance" && internalTab === "alarmes")

  useEffect(() => {
    oemApi.catalog().then(setCatalog).catch(() => setCatalog(null))
  }, [])

  useEffect(() => {
    if (draft.fromDate) return
    const today = dateFromIso(simNowIso) || new Date().toISOString().slice(0, 10)
    const shiftId = shifts[0]?.id ?? ""
    onChange({ ...draft, fromDate: today, toDate: today, fromShift: shiftId, toShift: shiftId })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simNowIso, shifts.length])

  if (collapsed) {
    return (
      <aside className="m-3 mr-2 flex w-11 shrink-0 flex-col items-center overflow-hidden rounded-2xl border border-border/80 bg-surface py-2 shadow-soft">
        <button
          type="button"
          className="flex size-7 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-foreground"
          title="Afficher les paramètres"
          onClick={() => setCollapsed(false)}
        >
          <ChevronRight className="size-3.5" />
        </button>
        <span className="mt-3 origin-center rotate-180 text-[11px] font-semibold uppercase tracking-wide text-foreground/80 [writing-mode:vertical-rl]">
          Paramètres
        </span>
      </aside>
    )
  }

  return (
    <aside
      className="m-3 mr-2 flex shrink-0 flex-col overflow-hidden rounded-2xl border border-border/80 bg-surface text-foreground shadow-soft"
      style={{ width: PANEL_WIDTH }}
    >
      <div className="sticky top-0 z-20 flex h-10 shrink-0 items-center justify-between bg-surface px-3">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80">Paramètres</span>
        <button
          type="button"
          className="flex size-7 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-foreground"
          onClick={() => setCollapsed(true)}
          title="Réduire"
        >
          <ChevronLeft className="size-3.5" />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 pb-3">
        <Field label="Entreprise">
          <Input className={CTL} value={siteName} disabled title="Le site se change dans l'en-tête MinePulse" />
        </Field>

        <Field label="Type d'équipement">
          <Select value={draft.equipmentType} onValueChange={(equipmentType) => onChange({ ...draft, equipmentType })}>
            <SelectTrigger className={CTL}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous</SelectItem>
              {types.map((t) => (
                <SelectItem key={t} value={t}>
                  {OEM_TYPE_GROUP[t] ?? t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Recherche">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3 -translate-y-1/2 text-muted-2" />
            <Input
              className="h-7 rounded-xl pl-7 text-xs"
              value={draft.equipmentSearch}
              onChange={(e) => onChange({ ...draft, equipmentSearch: e.target.value })}
              placeholder="ID…"
            />
          </div>
        </Field>

        <OemEquipmentTree
          equipment={equipment}
          typeFilter={draft.equipmentType}
          search={draft.equipmentSearch}
          selected={draft.equipmentCodes}
          onChange={(equipmentCodes) => onChange({ ...draft, equipmentCodes })}
        />

        <div className="overflow-hidden rounded-xl border border-border bg-background text-[11px] text-muted-2">
          <label className="flex items-center gap-2 border-b border-border px-3 py-2" title={UNAVAILABLE_SIM}>
            <input type="checkbox" disabled className="accent-accent" />
            Sous-traitants
          </label>
          <label className="flex items-center gap-2 px-3 py-2" title={UNAVAILABLE_SIM}>
            <input type="checkbox" disabled className="accent-accent" />
            Engins déclassés
          </label>
        </div>

        <Field label="Intervalle">
          <Select
            value={draft.periodMode}
            onValueChange={(periodMode) => onChange({ ...draft, periodMode: periodMode as OemDraft["periodMode"] })}
          >
            <SelectTrigger className={CTL}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="shift">Poste sélectionné</SelectItem>
              <SelectItem value="posts">Sur plusieurs postes</SelectItem>
              <SelectItem value="custom">Personnalisée</SelectItem>
            </SelectContent>
          </Select>
        </Field>

        {draft.periodMode === "posts" ? (
          <div className="flex flex-col gap-2">
            <div className="grid grid-cols-[1fr_88px] gap-1.5">
              <Input
                type="date"
                disabled
                className="h-7 rounded-xl px-2 text-xs"
                value={shifts.find((s) => s.id === draft.fromShift)?.windowStart?.slice(0, 10) ?? ""}
                onChange={(e) => onChange({ ...draft, fromDate: e.target.value })}
              />
              <Select
                value={draft.fromShift || undefined}
                onValueChange={(fromShift) => onChange({ ...draft, fromShift })}
              >
                <SelectTrigger className="h-7 w-full rounded-xl px-2 text-xs">
                  <SelectValue placeholder="Poste" />
                </SelectTrigger>
                <SelectContent>
                  {shifts.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-[1fr_88px] gap-1.5">
              <Input
                type="date"
                disabled
                className="h-7 rounded-xl px-2 text-xs"
                value={shifts.find((s) => s.id === draft.toShift)?.windowEnd?.slice(0, 10) ?? ""}
                onChange={(e) => onChange({ ...draft, toDate: e.target.value })}
              />
              <Select value={draft.toShift || undefined} onValueChange={(toShift) => onChange({ ...draft, toShift })}>
                <SelectTrigger className="h-7 w-full rounded-xl px-2 text-xs">
                  <SelectValue placeholder="Poste" />
                </SelectTrigger>
                <SelectContent>
                  {shifts.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        ) : null}

        {draft.periodMode === "custom" ? (
          <div className="flex flex-col gap-2">
            <Input
              type="datetime-local"
              className="h-7 rounded-xl px-2 text-xs"
              value={draft.from}
              onChange={(e) => onChange({ ...draft, from: e.target.value })}
            />
            <Input
              type="datetime-local"
              className="h-7 rounded-xl px-2 text-xs"
              value={draft.to}
              onChange={(e) => onChange({ ...draft, to: e.target.value })}
            />
          </div>
        ) : null}

        {showParams ? (
          <div>
            <span className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">
              Paramètres diagnostique
            </span>
            <div className="relative mb-1.5">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3 -translate-y-1/2 text-muted-2" />
              <Input
                className="h-7 rounded-xl pl-7 text-xs"
                placeholder="Recherche"
                value={draft.parameterSearch}
                onChange={(e) => onChange({ ...draft, parameterSearch: e.target.value })}
              />
            </div>
            <OemParameterSelector
              catalog={catalog}
              search={draft.parameterSearch}
              selected={draft.parameterKeys}
              equipmentType={draft.equipmentType}
              maxSelected={view === "diagnostic" && internalTab === "analyse" ? 4 : undefined}
              onChange={(parameterKeys) => onChange({ ...draft, parameterKeys })}
            />
          </div>
        ) : null}

        {showTyres ? (
          <div>
            <span className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">Positions pneus</span>
            <div className="overflow-hidden rounded-xl border border-border bg-background text-[11px]">
              {!catalog && <p className="p-2 text-muted">Catalogue indisponible ou en cours de chargement.</p>}
              {tyrePositions.map((p, i) => {
                const on = draft.tyrePositions.includes(p.code)
                return (
                  <label
                    key={p.code}
                    className={`flex cursor-pointer items-center gap-2 px-3 py-2 ${
                      i < tyrePositions.length - 1 ? "border-b border-border" : ""
                    } ${on ? "bg-accent-soft" : ""}`}
                  >
                    <input
                      type="checkbox"
                      className="accent-accent"
                      checked={on}
                      onChange={() =>
                        onChange({
                          ...draft,
                          tyrePositions: on
                            ? draft.tyrePositions.filter((x) => x !== p.code)
                            : [...draft.tyrePositions, p.code],
                        })
                      }
                    />
                    {p.labelFr}
                  </label>
                )
              })}
            </div>
          </div>
        ) : null}

        {showDelay ? (
          <Field label="Retard > (s)">
            <Input
              type="number"
              className={CTL}
              value={draft.minDelaySec}
              onChange={(e) => onChange({ ...draft, minDelaySec: Number(e.target.value) || 0 })}
            />
          </Field>
        ) : null}

        {showErrorFilters ? (
          <>
            <Field label="Sévérité">
              <Select value={draft.severity} onValueChange={(severity) => onChange({ ...draft, severity })}>
                <SelectTrigger className={CTL}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Toutes</SelectItem>
                  <SelectItem value="INFO">INFO</SelectItem>
                  <SelectItem value="WARNING">WARNING</SelectItem>
                  <SelectItem value="CRITICAL">CRITICAL</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            {view === "diagnostic" && internalTab === "erreurs" ? (
              <>
                <Field label="Catégorie">
                  <Select value={draft.category} onValueChange={(category) => onChange({ ...draft, category })}>
                    <SelectTrigger className={CTL}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Toutes</SelectItem>
                      <SelectItem value="moteur">Moteur</SelectItem>
                      <SelectItem value="pression">Pression</SelectItem>
                      <SelectItem value="électrique">Électrique</SelectItem>
                      <SelectItem value="carburant">Carburant</SelectItem>
                      <SelectItem value="communication">Communication</SelectItem>
                      <SelectItem value="pneus">Pneus</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Statut">
                  <Select
                    value={draft.statusFilter}
                    onValueChange={(statusFilter) => onChange({ ...draft, statusFilter })}
                  >
                    <SelectTrigger className={CTL}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Tous</SelectItem>
                      <SelectItem value="ACTIVE">Actif</SelectItem>
                      <SelectItem value="RESOLVED">Résolu</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
              </>
            ) : null}
          </>
        ) : null}
      </div>

      <div className="border-t border-border p-2.5">
        {exportCols && exportContext && exportName ? (
          <div className="mb-2">
            <OemExportButton
              rows={exportRows ?? []}
              columns={exportCols}
              context={exportContext}
              filename={exportName}
              compact
            />
          </div>
        ) : null}
        <Button className="h-8 w-full rounded-xl text-[11px] font-semibold" onClick={onApply}>
          Actualiser
        </Button>
      </div>
    </aside>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <span className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">{label}</span>
      {children}
    </div>
  )
}

import { useState } from "react"
import { Link } from "react-router-dom"
import { Check, MapPin, AlertTriangle, Monitor, Ruler, Target } from "lucide-react"

import { useOpsStore } from "@/lib/store/useOpsStore"
import { useApiMode } from "@/lib/api/client"
import { MERAH_SHIFT_SCENARIO } from "@/lib/mock/scenario"
import {
  formatRollupActual,
  formatRollupAttainment,
  formatRollupTarget,
  shiftProductionRollup,
} from "@/lib/production/mergeProduction"
import { cn } from "@/lib/utils"
import { StatusLegend } from "@/components/shared/StatusLegend"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export default function Parametres() {
  const settingsLoaded = useOpsStore((s) => s.settingsLoaded)
  const sites = useOpsStore((s) => s.sites)
  const shifts = useOpsStore((s) => s.shifts)
  const idleAlertThresholdMin = useOpsStore((s) => s.idleAlertThresholdMin)
  const setIdleAlertThreshold = useOpsStore((s) => s.setIdleAlertThreshold)
  const noCommThresholdMin = useOpsStore((s) => s.noCommThresholdMin)
  const setNoCommThreshold = useOpsStore((s) => s.setNoCommThreshold)
  const cycleDurationThresholdMin = useOpsStore((s) => s.cycleDurationThresholdMin)
  const setCycleDurationThreshold = useOpsStore((s) => s.setCycleDurationThreshold)
  const patchOperationalSetting = useOpsStore((s) => s.patchOperationalSetting)
  const density = useOpsStore((s) => s.density)
  const setDensity = useOpsStore((s) => s.setDensity)
  const unit = useOpsStore((s) => s.unit)
  const setUnit = useOpsStore((s) => s.setUnit)
  const productionByShift = useOpsStore((s) => s.productionByShift)
  const productionRollup = shiftProductionRollup(productionByShift)

  const [savedFlash, setSavedFlash] = useState(false)
  const [settingsError, setSettingsError] = useState<string | null>(null)

  function flash() {
    setSettingsError(null)
    setSavedFlash(true)
    setTimeout(() => setSavedFlash(false), 1500)
  }

  function handleNumber(
    value: string,
    setter: (n: number) => void,
    apiKey?: "idle_alert_threshold_min" | "no_comm_threshold_min" | "cycle_duration_threshold_min"
  ) {
    const num = Number(value)
    if (Number.isNaN(num) || num <= 0) return
    if (useApiMode && apiKey) {
      void patchOperationalSetting(apiKey, num)
        .then(flash)
        .catch(() => setSettingsError("Échec enregistrement — valeur serveur inchangée"))
    } else {
      setter(num)
      flash()
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-4">
        <div>
          <h1 className="text-base font-semibold text-foreground">Paramètres</h1>
          <p className="text-xs text-muted">
            Seuils d&apos;alerte, objectifs de poste, légende des états et affichage.
          </p>
        </div>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Seuils d&apos;alerte</CardTitle>
              <CardDescription>
                Détermine quand un engin est signalé dans Alertes IA / Film.
              </CardDescription>
            </div>
            <AlertTriangle className="size-4 text-muted-2" />
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {!settingsLoaded && <p className="text-xs text-muted">Paramètres serveur indisponibles ou en cours de chargement.</p>}
            <fieldset disabled={!settingsLoaded} hidden={!settingsLoaded} className="space-y-3">
            <ThresholdRow
              id="idle-threshold"
              label="Seuil d'attente prolongée"
              value={idleAlertThresholdMin}
              onChange={(v) => handleNumber(v, setIdleAlertThreshold, "idle_alert_threshold_min")}
            />
            <ThresholdRow
              id="nocomm-threshold"
              label="Seuil perte de communication"
              value={noCommThresholdMin}
              onChange={(v) => handleNumber(v, setNoCommThreshold, "no_comm_threshold_min")}
            />
            <ThresholdRow
              id="cycle-threshold"
              label="Seuil durée de cycle"
              value={cycleDurationThresholdMin}
              onChange={(v) => handleNumber(v, setCycleDurationThreshold, "cycle_duration_threshold_min")}
            />
            </fieldset>
            {savedFlash && (
              <span className="flex items-center gap-1 text-[11px] text-success">
                <Check className="size-3.5" />
                Enregistré
              </span>
            )}
            {settingsError && (
              <span className="text-[11px] text-danger">{settingsError}</span>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Objectifs de poste</CardTitle>
              <CardDescription>
                {useApiMode
                  ? "Objectifs et réalisé issus des services opérationnels."
                  : "Référence scénario Merah El Ahrach — matin 06:00–14:00."}
              </CardDescription>
            </div>
            <Target className="size-4 text-muted-2" />
          </CardHeader>
          <CardContent className="grid grid-cols-3 gap-3">
            {useApiMode ? (
              <>
                <TargetStat label="Objectif" value={formatRollupTarget(productionRollup)} />
                <TargetStat label="Réel" value={formatRollupActual(productionRollup)} />
                <TargetStat label="Atteinte" value={formatRollupAttainment(productionRollup)} />
              </>
            ) : (
              <>
                <TargetStat label="Objectif" value={`${MERAH_SHIFT_SCENARIO.targetTons.toLocaleString("fr-FR")} t`} />
                <TargetStat label="Réel (scénario)" value={`${MERAH_SHIFT_SCENARIO.actualTons.toLocaleString("fr-FR")} t`} />
                <TargetStat label="Atteinte" value={`${MERAH_SHIFT_SCENARIO.attainmentPct} %`} />
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Légende des états</CardTitle>
              <CardDescription>Référence Film / Carte — 8 groupes d’état.</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <StatusLegend />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Affichage</CardTitle>
              <CardDescription>Densité et unités pour les écrans de supervision.</CardDescription>
            </div>
            <Monitor className="size-4 text-muted-2" />
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-foreground/90">Densité des tables</p>
                <p className="text-[11px] text-muted">Les lignes compactes affichent plus de données sur grands écrans.</p>
              </div>
              <div className="flex rounded-md border border-border-strong bg-surface-2 p-0.5">
                {(["comfortable", "compact"] as const).map((d) => (
                  <button
                    key={d}
                    onClick={() => setDensity(d)}
                    className={cn(
                      "rounded-sm px-3 py-1 text-[11px] font-medium capitalize transition-colors",
                      density === d ? "bg-surface-3 text-foreground" : "text-muted-2"
                    )}
                  >
                    {d === "comfortable" ? "Confortable" : "Compact"}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Ruler className="size-3.5 text-muted-2" />
                <div>
                  <p className="text-xs font-medium text-foreground/90">Unités</p>
                  <p className="text-[11px] text-muted">Le système métrique est standard pour les opérations OCP.</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={cn("text-[11px]", unit === "metric" ? "text-foreground" : "text-muted-2")}>Métrique</span>
                <Switch disabled={useApiMode} checked={unit === "imperial"} onCheckedChange={(c) => setUnit(c ? "imperial" : "metric")} />
                <span className={cn("text-[11px]", unit === "imperial" ? "text-foreground" : "text-muted-2")}>{useApiMode ? "Conversion impériale non disponible" : "Impérial"}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Sites &amp; panneaux</CardTitle>
              <CardDescription>Données de référence des sites disponibles dans ce prototype.</CardDescription>
            </div>
            <MapPin className="size-4 text-muted-2" />
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Site</TableHead>
                  <TableHead>Région</TableHead>
                  <TableHead>Panneaux</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sites.map((site) => (
                  <TableRow key={site.id}>
                    <TableCell className="text-foreground/90">{site.name}</TableCell>
                    <TableCell className="text-muted">{site.region ?? "—"}</TableCell>
                    <TableCell className="text-muted">{site.pits.map((p) => p.name).join(", ") || "Non renseignés"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Grille des postes</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Poste</TableHead>
                  <TableHead>Début</TableHead>
                  <TableHead>Fin</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shifts.map((shift) => (
                  <TableRow key={shift.id}>
                    <TableCell className="text-foreground/90">{shift.name}</TableCell>
                    <TableCell className="tabular-nums text-muted">
                      {String(shift.startHour).padStart(2, "0")}:
                      {String(shift.startMinute ?? 0).padStart(2, "0")}
                    </TableCell>
                    <TableCell className="tabular-nums text-muted">
                      {String(shift.endHour).padStart(2, "0")}:
                      {String(shift.endMinute ?? 0).padStart(2, "0")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-2 text-[11px] text-muted-2">
          <div className="flex items-center gap-2">
            <Badge variant="outline">{useApiMode ? "API" : "Prototype"}</Badge>
            {useApiMode
              ? "Les seuils sont enregistrés via PATCH /api/settings/operational."
              : "Les paramètres sont stockés uniquement en état local — aucun backend n'est connecté."}
          </div>
          {import.meta.env.DEV && <Link
            to="/dev/simulation"
            className="text-accent underline-offset-2 hover:underline"
          >
            DEV — Centre de simulation (digital twin)
          </Link>}
        </div>
      </div>
    </div>
  )
}

function ThresholdRow({
  id,
  label,
  value,
  onChange,
}: {
  id: string
  label: string
  value: number
  onChange: (v: string) => void
}) {
  return (
    <div className="flex items-center gap-3">
      <Label htmlFor={id} className="w-56">
        {label}
      </Label>
      <Input
        id={id}
        type="number"
        min={1}
        className="w-24"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <span className="text-xs text-muted-2">minutes</span>
    </div>
  )
}

function TargetStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface-2/50 px-3 py-2">
      <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-2">{label}</p>
      <p className="mt-0.5 text-[14px] font-semibold tabular-nums text-foreground">{value}</p>
    </div>
  )
}

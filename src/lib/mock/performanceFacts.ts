import { MERAH_SHIFT_SCENARIO } from "./scenario"

const S = MERAH_SHIFT_SCENARIO

export function merahProductionFacts(
  actual: number,
  target: number | null,
  attainmentPct: number | null
): string[] {
  return [
    `${actual.toLocaleString("fr-FR")} / ${(target ?? 0).toLocaleString("fr-FR")} t (${attainmentPct} %)`,
    `Décrochage visible après 10:30 — congestion ${S.congestion.zoneName}`,
  ]
}

export function merahWaitingBancBKpi(): string {
  return `${S.congestion.truckCount}/3`
}

export function merahWaitingFacts(avgWait: number): string[] {
  return [`Attente flotte ~${avgWait.toFixed(0)} min`, `${S.congestion.zoneName} saturé depuis 10:30`]
}

export function merahDowntimeSpotlightRows() {
  return [
    {
      category: "Arrêt non défini",
      duration: Number((S.spotlight.stopMinutes / 60).toFixed(2)),
      cause: null,
      status: "Ouvert",
      equipment: S.spotlight.stopTruck,
    },
    {
      category: "Sans télémétrie",
      duration: Number((S.spotlight.noCommMinutes / 60).toFixed(2)),
      cause: "Communication",
      status: "Ouvert",
      equipment: S.spotlight.noCommTruck,
    },
    {
      category: "Maintenance",
      duration: 4.5,
      cause: "Arrêt matériel",
      status: "Confirmé",
      equipment: S.spotlight.maintExcavator,
    },
  ]
}

export function merahDowntimeKpis(): { id: string; label: string; value: string }[] {
  return [
    { id: "trk12", label: S.spotlight.stopTruck, value: `${S.spotlight.stopMinutes} min` },
    { id: "exc", label: S.spotlight.maintExcavator, value: "Maint." },
  ]
}

export function merahDowntimeFacts(): string[] {
  return [
    `${S.spotlight.stopTruck} arrêt non défini ~${S.spotlight.stopMinutes} min`,
    `${S.spotlight.maintExcavator} en maintenance — impact Banc B`,
  ]
}

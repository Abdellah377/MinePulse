import type { AlertSeverity } from "@/lib/mock/types"
import { useApiMode } from "@/lib/api/client"
import { MERAH_SHIFT_SCENARIO } from "@/lib/mock/scenario"

export type PredictionKind =
  | "saturation"
  | "production_drop"
  | "wait_increase"
  | "critical_unavailable"

export interface AiPrediction {
  id: string
  kind: PredictionKind
  severity: AlertSeverity
  category: string
  title: string
  summary: string
  zoneName: string | null
  equipmentCode: string | null
  horizonMin: number
  confidence: number
  probableCause: string
  signals: string[]
  impact: string
  suggestedAction: string
  status: "surveillance" | "escalade"
}

export function getMerahPredictions(): AiPrediction[] {
  if (useApiMode) return []
  const S = MERAH_SHIFT_SCENARIO
  return [
    {
      id: "pred-banc-b-sat",
      kind: "saturation",
      severity: "critical",
      category: "Congestion",
      title: `Risque de saturation ${S.congestion.zoneName} dans 18 min`,
      summary: `File actuelle ~${S.congestion.truckCount}/3 — tendance haussière depuis 10:30.`,
      zoneName: S.congestion.zoneName,
      equipmentCode: S.spotlight.maintExcavator,
      horizonMin: 18,
      confidence: 89,
      probableCause: `${S.spotlight.maintExcavator} en maintenance réduit la capacité de chargement ; arrivées non régulées.`,
      signals: [
        `Occupancy ${S.congestion.zoneName} > 200 %`,
        "Temps d'attente en hausse depuis 11:00",
        "Pas de rééquilibrage B → A encore préparé",
      ],
      impact: "Attentes +8–12 min · tonnage perdu estimé 40–60 t/h",
      suggestedAction: "Préparer une redirection partielle Banc B → Banc A",
      status: "escalade",
    },
    {
      id: "pred-prod-drop",
      kind: "production_drop",
      severity: "warning",
      category: "Production",
      title: "Risque de baisse de production d’ici 45 min",
      summary: `Atteinte actuelle ${S.attainmentPct} % — écart se creuse si congestion non traitée.`,
      zoneName: S.congestion.zoneName,
      equipmentCode: null,
      horizonMin: 45,
      confidence: 84,
      probableCause: "Retard cumulé Banc B + arrêts non classés (TRK-012) réduisent le rythme utile.",
      signals: [
        `${S.actualTons.toLocaleString("fr-FR")} / ${S.targetTons.toLocaleString("fr-FR")} t`,
        "Décrochage horaire après 10:30",
        S.narrative.next,
      ],
      impact: `Écart poste peut dépasser −${Math.round(S.targetTons - S.actualTons * 1.02)} t`,
      suggestedAction: "Générer un plan Actions IA ciblé congestion + arrêts",
      status: "surveillance",
    },
    {
      id: "pred-wait-up",
      kind: "wait_increase",
      severity: "warning",
      category: "Cycle",
      title: "Risque d’augmentation des attentes de chargement",
      summary: "Cycle moyen en dégradation — attente charge devient l’étape dominante.",
      zoneName: S.congestion.zoneName,
      equipmentCode: null,
      horizonMin: 25,
      confidence: 87,
      probableCause: "File Banc B + capacité pelle réduite allongent l’attente amont.",
      signals: [
        "Attente charge > cible sur plusieurs camions",
        `${S.spotlight.maintExcavator} hors service`,
        "Banc A sous-utilisé",
      ],
      impact: "Cycle +4–6 min · voyages/poste en baisse",
      suggestedAction: "Simuler un rééquilibrage de 3–4 camions vers Banc A",
      status: "escalade",
    },
    {
      id: "pred-crit-eq",
      kind: "critical_unavailable",
      severity: "info",
      category: "Maintenance",
      title: "Risque d’indisponibilité d’un équipement critique",
      summary: `${S.spotlight.maintExcavator} déjà en maintenance — ETA non confirmée.`,
      zoneName: S.congestion.zoneName,
      equipmentCode: S.spotlight.maintExcavator,
      horizonMin: 60,
      confidence: 76,
      probableCause: "Prolongation maintenance sans ETA claire maintient le goulot Banc B.",
      signals: [
        "Statut maintenance confirmé",
        "Pas d’heure de remise en service",
        "Pression file croissante",
      ],
      impact: "Capacité Banc B durablement limitée jusqu’à retour pelle",
      suggestedAction: "Confirmer ETA atelier et préparer plan de contournement",
      status: "surveillance",
    },
  ]
}

export function getPredictionById(id: string): AiPrediction | undefined {
  return getMerahPredictions().find((p) => p.id === id)
}

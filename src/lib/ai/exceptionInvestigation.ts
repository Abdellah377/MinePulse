import type { Alert } from "@/lib/mock/types"
import { useApiMode } from "@/lib/api/client"
import { MERAH_SHIFT_SCENARIO } from "@/lib/mock/scenario"

export type CauseKind = "confirmed" | "probable" | "hypothesis" | "insufficient"

export interface ExceptionInvestigation {
  facts: string[]
  probableCause: string
  causeKind: CauseKind
  supporting: string[]
  contradictory: string[]
  missing: string[]
  confidence: number
  verification: string
  ifIgnored: string
  impact: string
}

export function investigateException(alert: Alert, equipmentCode?: string | null): ExceptionInvestigation {
  if (useApiMode) throw new Error("Demo-only helper: use the investigation API")
  const code = equipmentCode ?? ""
  const S = MERAH_SHIFT_SCENARIO
  if (code === S.spotlight.noCommTruck || alert.category === "Communication") {
    return {
      facts: [
        `Aucune télémétrie depuis ~${S.spotlight.noCommMinutes} min`,
        `Dernière localisation : ${alert.location}`,
      ],
      probableCause: "Perte de lien radio / passerelle télématique",
      causeKind: "probable",
      supporting: ["Seuil no-comm atteint", "Pas de heartbeat GPS"],
      contradictory: ["Aucun message atelier confirmant panne capteur"],
      missing: ["Statut radio côté conducteur", "Log passerelle"],
      confidence: 91,
      verification: "Vérifier l'unité télématique et demander un check radio.",
      ifIgnored: "Engin invisible pour le dispatch — risque d'affectation incorrecte.",
      impact: "Perte de visibilité flotte · risque sécurité / régulation",
    }
  }
  if (code === S.spotlight.stopTruck || alert.category === "Arrêt") {
    return {
      facts: [
        `Arrêt depuis ~${S.spotlight.stopMinutes} min`,
        "Aucune cause déclarée à la radio",
      ],
      probableCause: "Arrêt non classé — possible attente hors zone après cycle Banc B",
      causeKind: "hypothesis",
      supporting: ["Corrélation temporelle avec congestion Banc B", "Pas de motif maintenance"],
      contradictory: ["Position hors Banc B (parking)"],
      missing: ["Motif conducteur", "Photo / cause OPM"],
      confidence: 84,
      verification: "Contacter le conducteur et classer la cause d'arrêt.",
      ifIgnored: "Temps productif perdu non expliqué · KPI arrêt sans cause.",
      impact: "Indisponibilité camion · contribution au retard poste",
    }
  }
  if (code === S.spotlight.maintExcavator || alert.category === "Maintenance") {
    return {
      facts: [`${S.spotlight.maintExcavator} en arrêt matériel`, "Maintenance confirmée"],
      probableCause: "Arrêt matériel planifié / en cours — capacité Banc B réduite",
      causeKind: "confirmed",
      supporting: ["Statut maintenance", `File Banc B ~${S.congestion.truckCount} camions`],
      contradictory: [],
      missing: ["ETA retour en service"],
      confidence: 95,
      verification: "Confirmer l'heure de remise en service avec l'atelier.",
      ifIgnored: "Congestion Banc B se prolonge · écart production s'aggrave.",
      impact: "Goulot de chargement · −11 % atteinte poste",
    }
  }
  if (alert.category === "Congestion") {
    return {
      facts: [
        `${S.congestion.zoneName} : file ~${S.congestion.truckCount} / cap. 3`,
        `${S.spotlight.maintExcavator} indisponible`,
      ],
      probableCause: "Saturation de file liée à la perte de capacité pelle",
      causeKind: "probable",
      supporting: S.narrative.evidence.slice(0, 3),
      contradictory: ["Banc A sous-utilisé"],
      missing: ["Nombre exact de camions redirigables sans casser le cycle A"],
      confidence: 88,
      verification: "Préparer une optimisation B → A et valider avec le régulateur.",
      ifIgnored: S.narrative.next,
      impact: "Attente élevée · tonnage perdu estimé",
    }
  }
  return {
    facts: [alert.description, `Localisation : ${alert.location}`],
    probableCause: `Anomalie « ${alert.category} » dans le contexte du retard de production (−11 %)`,
    causeKind: "hypothesis",
    supporting: S.narrative.evidence.slice(0, 2),
    contradictory: [],
    missing: ["Cause enregistrée côté terrain"],
    confidence: 72,
    verification: "Collecter la cause terrain puis mettre à jour l'événement.",
    ifIgnored: "Risque de non-apprentissage et de récurrence.",
    impact: "À évaluer selon durée et équipement",
  }
}

export const CAUSE_KIND_LABEL: Record<CauseKind, string> = {
  confirmed: "Cause enregistrée",
  probable: "Cause probable",
  hypothesis: "Hypothèse à confirmer",
  insufficient: "Données insuffisantes",
}

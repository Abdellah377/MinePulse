import type { AiInsight } from "@/components/ai/AiSlot"
import { useApiMode } from "@/lib/api/client"
import { MERAH_SHIFT_SCENARIO } from "@/lib/mock/scenario"

function hashString(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

function pickFrom<T>(seed: string, arr: readonly T[]): T {
  return arr[hashString(seed) % arr.length]
}

function confidenceFrom(seed: string, min = 70, max = 96) {
  return min + (hashString(seed) % Math.max(1, max - min))
}

const DISABLED_AI: AiInsight = {
  title: "Analyse IA non activée",
  body: "Ouvrez Alertes IA pour démarrer ou consulter une investigation enregistrée.",
  evidence: [],
  next: "Activer le moteur IA pour des hypothèses.",
  action: "Consulter Film / Carte / Alertes",
}


/** Slot IA — panneau détail Film (segment sélectionné). */
export function filmSegmentInsight(seed: string, stateLabel: string): AiInsight {
  if (useApiMode) {
    return {
      title: `État — ${stateLabel}`,
      body: "Analyse IA non activée — contexte factuel uniquement.",
      evidence: [],
      next: "Activer le moteur IA pour des hypothèses.",
      action: "Vérifier sur Film / Carte",
    }
  }
  const S = MERAH_SHIFT_SCENARIO
  const causes = [
    `File Banc B saturée (~${S.congestion.truckCount} camions) — ${S.spotlight.maintExcavator} en maintenance.`,
    `${S.spotlight.stopTruck} en arrêt non défini allonge la file amont.`,
    "Cycle amont ralenti après 11:00 — attentes de chargement en hausse.",
    "Relève / régulation manuelle en cours sur la zone concernée.",
  ] as const
  return {
    title: `Raison probable — ${stateLabel}`,
    body: pickFrom(seed, causes),
    confidence: confidenceFrom(seed),
    evidence: [
      `Congestion ${S.congestion.zoneName} depuis 10:30`,
      `${S.spotlight.maintExcavator} hors service`,
    ],
    next: S.narrative.next,
    action: S.narrative.action,
  }
}

/** Slot IA — expand Cycle actuel / onglet Cycle (Inspecteur). */
export function cycleLongInsight(seed: string): AiInsight {
  if (useApiMode) return { ...DISABLED_AI, title: "Cycle — analyse IA non activée" }
  const S = MERAH_SHIFT_SCENARIO
  const causes = [
    "Temps d'attente de chargement supérieur à la moyenne — Banc B saturé.",
    "Trajet allongé par la congestion piste après 10:30.",
    "EXC-027 en maintenance réduit la capacité de chargement Banc B.",
  ] as const
  return {
    title: "Pourquoi ce cycle est long ?",
    body: pickFrom(seed, causes),
    confidence: confidenceFrom(seed, 65, 92),
    evidence: [
      "Cycle moyen en hausse après 11:00",
      `Banc B ~${S.congestion.truckCount} camions en file`,
    ],
    action: S.narrative.action,
  }
}

/** Slot IA — panneau détail Événements. */
export function evenementInsight(seed: string, category: string): AiInsight {
  if (useApiMode) return { ...DISABLED_AI, title: `Événement — ${category}` }
  const S = MERAH_SHIFT_SCENARIO
  const byCat: Record<string, string> = {
    Arrêt: `${S.spotlight.stopTruck} sans cause déclarée (~${S.spotlight.stopMinutes} min) — corrélé à la congestion Banc B.`,
    Communication: `${S.spotlight.noCommTruck} sans télémétrie (~${S.spotlight.noCommMinutes} min) — vérifier radio / passerelle.`,
    Congestion: `${S.congestion.zoneName} saturé depuis 10:30 avec ${S.spotlight.maintExcavator} en maintenance.`,
    Maintenance: `${S.spotlight.maintExcavator} immobilisé — capacité Banc B réduite.`,
    Cycle: "Dégradation du cycle après 11:00 liée aux attentes de chargement Banc B.",
  }
  return {
    title: "Explication",
    body:
      byCat[category] ??
      `Anomalie « ${category} » dans le contexte du retard de production (−11 %) sur Merah El Ahrach.`,
    confidence: confidenceFrom(seed, 60, 90),
    evidence: S.narrative.evidence.slice(0, 2),
    action: S.narrative.action,
  }
}

/** Chips IA — Carte / Info rapide (selection-only; kept for fallback). */
export function carteChipInsights(_seed: string): AiInsight[] {
  if (useApiMode) return []
  const S = MERAH_SHIFT_SCENARIO
  return [
    {
      title: "Congestion Banc B",
      body: `~${S.congestion.truckCount} camions en file depuis 10:30.`,
      confidence: 90,
    },
    {
      title: `${S.spotlight.stopTruck} arrêté`,
      body: `Arrêt non défini ~${S.spotlight.stopMinutes} min.`,
      confidence: 86,
    },
    {
      title: "Rediriger B → A",
      body: S.narrative.action,
      confidence: 88,
    },
  ]
}

/** Slot IA — brief Exceptions / poste. */
export function posteSummaryInsight(_seed: string): AiInsight {
  if (useApiMode) return { ...DISABLED_AI, title: "Synthèse poste" }
  const S = MERAH_SHIFT_SCENARIO
  return {
    title: S.narrative.headline,
    body: S.narrative.body,
    confidence: 88,
    evidence: S.narrative.evidence,
    next: S.narrative.next,
    action: S.narrative.action,
  }
}

/** Slot IA — onglet IA (Inspecteur). */
export function inspecteurInsight(seed: string, code: string): AiInsight {
  if (useApiMode) return { ...DISABLED_AI, title: `Inspecteur — ${code}` }
  const S = MERAH_SHIFT_SCENARIO
  if (code === S.spotlight.stopTruck) {
    return {
      title: `Pourquoi — ${code}`,
      body: `Arrêt non défini depuis ~${S.spotlight.stopMinutes} min sans cause radio. Probable attente hors zone après cycle Banc B.`,
      confidence: 84,
      evidence: ["Aucune cause déclarée", "Dernier cycle via Banc B"],
      next: "Sans contact conducteur, l'arrêt reste hors production.",
      action: "Contacter le conducteur et classer la cause d'arrêt.",
    }
  }
  if (code === S.spotlight.noCommTruck) {
    return {
      title: `Pourquoi — ${code}`,
      body: `Aucune télémétrie depuis ~${S.spotlight.noCommMinutes} min — seuil communication atteint.`,
      confidence: 91,
      evidence: ["Dernière position près Banc A", "Pas de heartbeat GPS"],
      action: "Vérifier l'unité télématique / radio.",
    }
  }
  if (code === S.spotlight.maintExcavator) {
    return {
      title: `Pourquoi — ${code}`,
      body: "Arrêt matériel — maintenance en atelier. Capacité Banc B réduite.",
      confidence: 95,
      evidence: ["Statut maintenance confirmé", "File Banc B en tension"],
      action: S.narrative.action,
    }
  }
  return {
    title: `Pourquoi — ${code}`,
    body: "Temps d'attente supérieur à la moyenne, lié à la saturation Banc B et à EXC-027 hors service.",
    confidence: confidenceFrom(seed, 68, 95),
    evidence: ["Attente > seuil", "Banc B en congestion"],
    next: S.narrative.next,
    action: S.narrative.action,
  }
}

/** Slot IA — résumé Performance. */
export function performanceInsight(_seed: string): AiInsight {
  if (useApiMode) return { ...DISABLED_AI, title: "Performance" }
  const S = MERAH_SHIFT_SCENARIO
  return {
    title: "Le cycle se dégrade après 11:00",
    body: `L'attente au Banc B porte la majorité du retard (7 231 / 8 160 t). ${S.spotlight.maintExcavator} en maintenance et la congestion depuis 10:30 expliquent la baisse.`,
    confidence: 87,
    evidence: S.narrative.evidence.slice(0, 3),
    next: S.narrative.next,
    action: S.narrative.action,
  }
}

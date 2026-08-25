import { resolveOemView } from "@/lib/oem/types"
import type {
  OpenWorkspaceInput,
  PerformanceMetric,
  WorkspaceContext,
  WorkspaceType,
} from "@/lib/workspace/types"

const METRIC_LABEL: Record<PerformanceMetric, string> = {
  production: "Production",
  fuel: "Gasoil",
  cycle: "Cycle moyen",
  waiting: "Temps d'attente",
  td: "TD",
  tu: "TU",
  downtime: "Arrêts",
  voyages: "Voyages",
}

const OEM_IDENTITY: Record<string, string> = {
  connectivite: "connectivity",
  diagnostic: "diagnostic",
  maintenance: "maintenance",
  pneus: "tyres",
  "vitesse-gasoil": "speed-fuel",
  poids: "payload-speed-fuel",
  multi: "multi",
}

export function contextDedupeKey(type: WorkspaceType, context: WorkspaceContext = {}): string {
  const parts: string[] = [type]
  if (type === "oem") {
    const view = resolveOemView(context.oemView as string | undefined)
    const slug = OEM_IDENTITY[view] ?? view
    if (view === "connectivite") {
      parts.push("connectivity")
    } else {
      parts.push(`${slug}:${context.equipmentCode ?? "_"}`)
    }
    if (context.investigationId) parts.push(`inv:${context.investigationId}`)
    if (context._dup) parts.push(`dup:${String(context._dup)}`)
    return parts.join("|")
  }
  if (context.equipmentId) parts.push(`eq:${context.equipmentId}`)
  else if (context.equipmentCode) parts.push(`code:${context.equipmentCode}`)
  if (context.zoneId) parts.push(`zone:${context.zoneId}`)
  else if (context.zoneName) parts.push(`zn:${context.zoneName}`)
  if (context.alertId) parts.push(`alert:${context.alertId}`)
  if (context.predictionId) parts.push(`pred:${context.predictionId}`)
  if (context.metric) parts.push(`metric:${context.metric}`)
  if (context.investigationId) parts.push(`inv:${context.investigationId}`)
  if (parts.length === 1) parts.push("home")
  return parts.join("|")
}

const OEM_VIEW_TITLE: Record<string, string> = {
  connectivite: "Connectivité",
  diagnostic: "Diagnostic machine",
  maintenance: "Maintenance",
  pneus: "Pression pneus",
  "vitesse-gasoil": "Vitesse & gasoil",
  poids: "Poids / vitesse / carburant",
  multi: "Multi-paramètres",
}

export function oemViewTitle(view: string | undefined): string {
  return OEM_VIEW_TITLE[resolveOemView(view)] ?? "OEM"
}

export function buildWorkspaceTitle(input: OpenWorkspaceInput): string {
  if (input.title) return input.title
  const ctx = input.context ?? {}
  const focus =
    ctx.equipmentCode ??
    ctx.zoneName ??
    (typeof ctx.titleFocus === "string" ? ctx.titleFocus : undefined) ??
    (ctx.metric ? METRIC_LABEL[ctx.metric as PerformanceMetric] : undefined)

  switch (input.type) {
    case "alerts":
      if (ctx.predictionId) return focus ? `Prédiction — ${focus}` : "Prédictions IA"
      return focus ? `${focus}` : "Alertes IA"
    case "map":
      return focus ? `Carte — ${focus}` : "Carte"
    case "timeline":
      return focus ? `Film — ${focus}` : "Film"
    case "performance":
      return focus ? `Performance — ${focus}` : "Performance — Production"
    case "oem": {
      const view = resolveOemView(ctx.oemView as string | undefined)
      const viewLabel = OEM_VIEW_TITLE[view] ?? "OEM"
      if (view === "connectivite") return viewLabel
      return focus ? `${viewLabel} — ${focus}` : viewLabel
    }
    case "actions":
      return focus ? `Actions IA — ${focus}` : "Actions IA"
    case "settings":
      return "Paramètres"
    default:
      return "Espace de travail"
  }
}

export function performanceMetricLabel(metric: PerformanceMetric): string {
  return METRIC_LABEL[metric]
}

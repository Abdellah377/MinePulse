import { resolveOemView } from "@/lib/oem/types"
import type {
  OpenWorkspaceInput,
  PerformanceMetric,
  WorkspaceContext,
  WorkspaceTab,
  WorkspaceType,
} from "@/lib/workspace/types"
import { MODULE_HOME, WORKSPACE_TYPE_MODULE } from "@/lib/workspace/types"

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

/** Stable identity for a module-home workspace. Independent of selection patches. */
export function moduleHomeDedupeKey(type: WorkspaceType): string {
  if (type === "oem") return "oem|connectivity"
  return `${type}|home`
}

export function canonicalHomeTitle(type: WorkspaceType): string {
  const module = WORKSPACE_TYPE_MODULE[type]
  const home = MODULE_HOME[module]
  if (home.type === type) return home.title
  return buildWorkspaceTitle({ type })
}

/**
 * Identity that distinguishes a contextual workspace from module home.
 * Metric and OEM connectivité are in-page / home, not a new workspace.
 */
export function hasContextualIdentity(type: WorkspaceType, context: WorkspaceContext = {}): boolean {
  if (type === "oem") {
    return resolveOemView(context.oemView as string | undefined) !== "connectivite"
  }
  return Boolean(
    context.equipmentId ||
      context.equipmentCode ||
      context.zoneId ||
      context.zoneName ||
      context.alertId ||
      context.predictionId ||
      context.investigationId,
  )
}

export function isModuleHomeContext(type: WorkspaceType, context: WorkspaceContext = {}): boolean {
  if (context._dup) return false
  if (context._home === true) return true
  return !hasContextualIdentity(type, context)
}

export function isModuleHomeTab(tab: Pick<WorkspaceTab, "type" | "title" | "context">): boolean {
  if (tab.context._dup) return false
  if (isModuleHomeContext(tab.type, tab.context)) return true
  // Mutated homes keep the canonical title (e.g. Alertes IA) after selection patches.
  return tab.title === canonicalHomeTitle(tab.type)
}

/** Stamp or strip `_home` so contextual opens never inherit a home flag. */
export function prepareWorkspaceContext(type: WorkspaceType, context: WorkspaceContext = {}): WorkspaceContext {
  if (context._dup) {
    const { _home: _ignored, ...rest } = context
    return rest
  }
  if (hasContextualIdentity(type, context)) {
    const { _home: _ignored, ...rest } = context
    return rest
  }
  return { ...context, _home: true }
}

export function contextDedupeKey(type: WorkspaceType, context: WorkspaceContext = {}): string {
  const prepared = context
  if (isModuleHomeContext(type, prepared) && !prepared._dup) {
    return moduleHomeDedupeKey(type)
  }
  const parts: string[] = [type]
  if (type === "oem") {
    const view = resolveOemView(prepared.oemView as string | undefined)
    const slug = OEM_IDENTITY[view] ?? view
    if (view === "connectivite") {
      parts.push("connectivity")
    } else {
      parts.push(`${slug}:${prepared.equipmentCode ?? "_"}`)
    }
    if (prepared.investigationId) parts.push(`inv:${prepared.investigationId}`)
    if (prepared._dup) parts.push(`dup:${String(prepared._dup)}`)
    return parts.join("|")
  }
  if (prepared.equipmentId) parts.push(`eq:${prepared.equipmentId}`)
  else if (prepared.equipmentCode) parts.push(`code:${prepared.equipmentCode}`)
  if (prepared.zoneId) parts.push(`zone:${prepared.zoneId}`)
  if (prepared.zoneName && !prepared.zoneId) parts.push(`zn:${prepared.zoneName}`)
  if (prepared.alertId) parts.push(`alert:${prepared.alertId}`)
  if (prepared.predictionId) parts.push(`pred:${prepared.predictionId}`)
  if (prepared.investigationId) parts.push(`inv:${prepared.investigationId}`)
  if (parts.length === 1) parts.push("home")
  if (prepared._dup) parts.push(`dup:${String(prepared._dup)}`)
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

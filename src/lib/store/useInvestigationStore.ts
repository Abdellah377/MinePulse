import { create } from "zustand"
import { ApiError, ApiTimeoutError, ApiNetworkError } from "@/lib/api/client"
import { aiApi, type InvestigationScope } from "@/lib/api/ai"
import type { InvestigationResult, InvestigationTriggerInput } from "@/lib/api/types/ai"

export type InvestigationEntry = {
  phase: "loading" | "absent" | "running" | "ready" | "error"
  result?: InvestigationResult
  error?: string
  /** A transport failure after POST does not prove the server stopped working. */
  creationUncertain?: boolean
}

export function investigationKey(scope: InvestigationScope): string {
  return `${scope.site_id}:${scope.shift_id ?? "any"}:${scope.source_record_id}`
}

function errorLabel(error: unknown): string {
  if (error instanceof ApiTimeoutError) return "Délai de l’analyse IA dépassé. Investigation enregistrée en échec ; actualisez ou relancez."
  if (error instanceof ApiNetworkError) return "Backend injoignable. Vérifiez la connexion au serveur."
  if (error instanceof ApiError) {
    switch (error.code) {
      case "AI_STORAGE_NOT_READY": return "Stockage IA non initialisé. Appliquez les migrations du backend."
      case "AI_STORAGE_UNAVAILABLE": return "Base de données des investigations indisponible."
      case "AI_PROVIDER_NOT_CONFIGURED": return "Fournisseur IA non configuré. Renseignez AI_PROVIDER_ORDER ou AI_PROVIDER, plus la clé et le modèle du fournisseur, côté serveur."
      case "AI_PERSISTENCE_FAILED": return "Échec de l’enregistrement de l’investigation. Consultez les journaux serveur."
      case "AI_INVESTIGATION_FAILED": return "Investigation échouée côté serveur. Consultez les journaux serveur."
    }
    if ([502, 504].includes(error.status)) return "Passerelle backend indisponible ou délai serveur dépassé."
    if (error.status >= 500 && error.status !== 503) return "Erreur interne du backend. Consultez les journaux serveur."
  }
  if (error instanceof ApiError && error.status === 503) return "Service d’investigation indisponible. Consultez les journaux serveur."
  if (error instanceof ApiError && error.status === 404) return "Investigation ou contexte opérationnel introuvable."
  if (error instanceof ApiError && error.status === 422) return "Contexte de l’investigation invalide."
  return "Requête d’investigation échouée. Aucun résultat IA n’a été substitué."
}

// Shared across component mounts/workspaces. Effects can read, but never create.
const inFlight = new Map<string, Promise<void>>()
interface InvestigationStore {
  entries: Record<string, InvestigationEntry>
  lookup: (scope: InvestigationScope, refresh?: boolean) => Promise<void>
  retrieve: (id: string, refresh?: boolean) => Promise<void>
  start: (trigger: InvestigationTriggerInput, options?: { retryFailed?: boolean }) => Promise<void>
}

export const useInvestigationStore = create<InvestigationStore>((set, get) => {
  const put = (key: string, entry: InvestigationEntry) => set((s) => ({ entries: { ...s.entries, [key]: entry } }))
  const save = (key: string, result: InvestigationResult) => {
    put(key, { phase: "ready", result })
    put(result.investigation_id, { phase: "ready", result })
  }
  const once = (key: string, run: () => Promise<void>) => {
    const existing = inFlight.get(key)
    if (existing) return existing
    const promise = Promise.resolve().then(run).finally(() => inFlight.delete(key))
    inFlight.set(key, promise)
    return promise
  }
  return {
    entries: {},
    lookup(scope, refresh = false) {
      const key = investigationKey(scope)
      return once(`lookup:${key}`, async () => {
        const previous = get().entries[key]
        if (previous && !refresh) return
        put(key, { ...previous, phase: previous?.phase === "running" ? "running" : "loading" })
        try {
          const results = await aiApi.find(scope)
          const latest = get().entries[key]
          if (results[0]) save(key, results[0])
          else if (latest?.result) save(key, latest.result)
          else if (latest?.phase === "running") put(key, { phase: "running" })
          else if (latest?.creationUncertain || previous?.creationUncertain) put(key, {
            phase: "error", creationUncertain: true,
            error: "Résultat pas encore enregistré. L’exécution peut continuer côté serveur ; actualisez sans relancer.",
          })
          else put(key, { phase: "absent" })
        } catch (error) {
          const latest = get().entries[key]
          if (latest?.result) put(key, { phase: "error", result: latest.result, error: errorLabel(error), creationUncertain: latest.creationUncertain })
          else if (latest?.phase === "running") put(key, { phase: "running", creationUncertain: latest.creationUncertain })
          else put(key, { ...latest, phase: "error", error: errorLabel(error), creationUncertain: latest?.creationUncertain ?? previous?.creationUncertain })
        }
      })
    },
    retrieve(id, refresh = false) {
      return once(`retrieve:${id}`, async () => {
        if (get().entries[id] && !refresh) return
        const previous = get().entries[id]
        put(id, { ...previous, phase: "loading" })
        try { save(id, await aiApi.get(id)) }
        catch (error) { put(id, { ...previous, phase: "error", error: errorLabel(error) }) }
      })
    },
    start(trigger, options) {
      const retryFailed = options?.retryFailed === true
      const scope = { site_id: trigger.site_id, shift_id: trigger.shift_id, source_record_id: trigger.source_record_id ?? "" }
      const key = investigationKey(scope)
      return once(`start:${key}`, async () => {
        const previous = get().entries[key]
        if (previous?.creationUncertain) return
        if (previous?.result && previous.result.status !== "FAILED") return
        if (previous?.result?.status === "FAILED" && !retryFailed) return
        put(key, { phase: "loading" })
        let posted = false
        try {
          const existing = await aiApi.find(scope)
          const latest = existing[0]
          if (latest && latest.status !== "FAILED") { save(key, latest); return }
          if (latest?.status === "FAILED" && !retryFailed) { save(key, latest); return }
          put(key, { phase: "running" })
          posted = true
          save(key, await aiApi.create(trigger))
        } catch (error) {
          const rejectedBeforeRun = error instanceof ApiError && (
            [400, 404, 422].includes(error.status) ||
            ["AI_PROVIDER_NOT_CONFIGURED", "AI_STORAGE_NOT_READY"].includes(error.code ?? "")
          )
          put(key, { phase: "error", error: errorLabel(error), creationUncertain: posted && !rejectedBeforeRun })
        }
      })
    },
  }
})

import { create } from "zustand"
import { persist, createJSONStorage, type StateStorage } from "zustand/middleware"

import {
  buildWorkspaceTitle,
  contextDedupeKey,
  isModuleHomeContext,
  isModuleHomeTab,
  moduleHomeDedupeKey,
  prepareWorkspaceContext,
} from "@/lib/workspace/titles"
import {
  MODULE_HOME,
  WORKSPACE_TYPE_MODULE,
  type OpenWorkspaceInput,
  type WorkspaceModule,
  type WorkspaceTab,
} from "@/lib/workspace/types"

export const WORKSPACE_PERSIST_VERSION = 5
const PERSIST_NAME = `minepulse.workspaces.v${WORKSPACE_PERSIST_VERSION}`
const LEGACY_PERSIST_NAMES = ["minepulse.workspaces.v4"]

type TabStateMap = Record<string, Record<string, unknown>>

interface WorkspaceState {
  tabs: WorkspaceTab[]
  activeTabId: string | null
  tabState: TabStateMap
  /** Stable dedupe index: key -> tabId */
  dedupeIndex: Record<string, string>

  openWorkspace: (input: OpenWorkspaceInput) => string
  openModuleHome: (module: WorkspaceModule) => string
  activateTab: (id: string) => void
  closeTab: (id: string) => boolean
  closeOthers: (id: string) => void
  closeToRight: (id: string) => void
  duplicateTab: (id: string) => string | null
  pinTab: (id: string, pinned?: boolean) => void
  reorderTabs: (fromIndex: number, toIndex: number) => void
  setTabDirty: (id: string, dirty: boolean) => void
  setTabTitle: (id: string, title: string) => void
  patchTabContext: (id: string, patch: Record<string, unknown>) => void
  setTabState: (id: string, partial: Record<string, unknown>) => void
  getTabState: (id: string) => Record<string, unknown>
  nextTab: () => void
  prevTab: () => void
  activateByIndex: (index: number) => void
}

function uid() {
  return `ws-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
}

const initialHome = MODULE_HOME.alertes
const initialId = "ws-home-alertes"
const initialTab: WorkspaceTab = {
  id: initialId,
  type: initialHome.type,
  title: initialHome.title,
  module: "alertes",
  context: initialHome.context ?? { _home: true },
  isPinned: false,
  isDirty: false,
  createdAt: Date.now(),
  lastActivatedAt: Date.now(),
}

function sortTabs(tabs: WorkspaceTab[]): WorkspaceTab[] {
  const pinned = tabs.filter((t) => t.isPinned)
  const rest = tabs.filter((t) => !t.isPinned)
  return [...pinned, ...rest]
}

function rebuildIndex(tabs: WorkspaceTab[]): Record<string, string> {
  const idx: Record<string, string> = {}
  for (const t of tabs) {
    idx[contextDedupeKey(t.type, t.context)] = t.id
  }
  return idx
}

function pickHomeWinner(homes: WorkspaceTab[], activeTabId: string | null): WorkspaceTab {
  const active = homes.find((h) => h.id === activeTabId)
  if (active) return active
  const pinned = homes
    .filter((h) => h.isPinned)
    .sort((a, b) => b.lastActivatedAt - a.lastActivatedAt)
  if (pinned[0]) return pinned[0]
  return [...homes].sort((a, b) => b.lastActivatedAt - a.lastActivatedAt)[0]
}

/** Collapse duplicate module-home tabs. Contextual and intentional copies are kept. */
export function normalizeDuplicateHomeTabs(
  tabs: WorkspaceTab[],
  activeTabId: string | null,
): { tabs: WorkspaceTab[]; activeTabId: string | null; droppedIds: string[] } {
  if (tabs.length === 0) {
    return { tabs: [initialTab], activeTabId: initialTab.id, droppedIds: [] }
  }
  const groups = new Map<string, WorkspaceTab[]>()
  for (const tab of tabs) {
    if (!isModuleHomeTab(tab)) continue
    const key = moduleHomeDedupeKey(tab.type)
    const list = groups.get(key) ?? []
    list.push(tab)
    groups.set(key, list)
  }
  const droppedIds: string[] = []
  const winnerById = new Map<string, WorkspaceTab>()
  for (const homes of groups.values()) {
    const stamped = homes.map((h) => ({ ...h, context: { ...h.context, _home: true } }))
    const winner = pickHomeWinner(stamped, activeTabId)
    winnerById.set(winner.id, winner)
    for (const h of stamped) {
      if (h.id !== winner.id) droppedIds.push(h.id)
    }
  }
  const dropped = new Set(droppedIds)
  const nextTabs = tabs.flatMap((t) => {
    if (dropped.has(t.id)) return []
    return [winnerById.get(t.id) ?? t]
  })
  if (nextTabs.length === 0) {
    return { tabs: [initialTab], activeTabId: initialTab.id, droppedIds }
  }
  const nextActive =
    activeTabId && nextTabs.some((t) => t.id === activeTabId) ? activeTabId : nextTabs[0]?.id ?? null
  return { tabs: sortTabs(nextTabs), activeTabId: nextActive, droppedIds }
}

function pruneTabState(tabState: TabStateMap, tabs: WorkspaceTab[]): TabStateMap {
  const keep = new Set(tabs.map((t) => t.id))
  const next: TabStateMap = {}
  for (const [id, value] of Object.entries(tabState)) {
    if (keep.has(id)) next[id] = value
  }
  return next
}

function findExistingTabId(
  tabs: WorkspaceTab[],
  dedupeIndex: Record<string, string>,
  activeTabId: string | null,
  type: WorkspaceTab["type"],
  context: WorkspaceTab["context"],
  key: string,
): string | null {
  const byKey = dedupeIndex[key]
  if (byKey && tabs.some((t) => t.id === byKey)) return byKey
  if (!isModuleHomeContext(type, context)) return null
  const homes = tabs.filter((t) => t.type === type && isModuleHomeTab(t))
  if (homes.length === 0) return null
  return pickHomeWinner(homes, activeTabId).id
}

type PersistedWorkspace = {
  tabs?: WorkspaceTab[]
  activeTabId?: string | null
  tabState?: TabStateMap
  dedupeIndex?: Record<string, string>
}

function applyPersistedWorkspace(persisted: PersistedWorkspace, fallback: WorkspaceState): Pick<
  WorkspaceState,
  "tabs" | "activeTabId" | "tabState" | "dedupeIndex"
> {
  const tabs = Array.isArray(persisted.tabs) ? persisted.tabs : []
  if (tabs.length === 0) {
    return {
      tabs: fallback.tabs,
      activeTabId: fallback.activeTabId,
      tabState: fallback.tabState,
      dedupeIndex: fallback.dedupeIndex,
    }
  }
  const normalized = normalizeDuplicateHomeTabs(tabs, persisted.activeTabId ?? null)
  return {
    tabs: normalized.tabs,
    activeTabId: ensureActive(normalized.tabs, normalized.activeTabId),
    tabState: pruneTabState(persisted.tabState ?? {}, normalized.tabs),
    dedupeIndex: rebuildIndex(normalized.tabs),
  }
}

function liveSessionStorage(): Storage | null {
  try {
    if (typeof sessionStorage === "undefined") return null
    return sessionStorage
  } catch {
    return null
  }
}

function workspaceStorage(): StateStorage {
  const memory = new Map<string, string>()
  return {
    getItem: (name) => {
      const ss = liveSessionStorage()
      if (ss) {
        const current = ss.getItem(name)
        if (current != null) return current
        for (const legacy of LEGACY_PERSIST_NAMES) {
          const value = ss.getItem(legacy)
          if (value != null) return value
        }
        return null
      }
      return memory.get(name) ?? null
    },
    setItem: (name, value) => {
      const ss = liveSessionStorage()
      if (ss) ss.setItem(name, value)
      else memory.set(name, value)
    },
    removeItem: (name) => {
      const ss = liveSessionStorage()
      if (ss) ss.removeItem(name)
      else memory.delete(name)
    },
  }
}

function ensureActive(tabs: WorkspaceTab[], activeTabId: string | null): string | null {
  if (tabs.length === 0) return null
  if (activeTabId && tabs.some((t) => t.id === activeTabId)) return activeTabId
  return tabs[0]?.id ?? null
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set, get) => ({
      tabs: [initialTab],
      activeTabId: initialId,
      tabState: {},
      dedupeIndex: rebuildIndex([initialTab]),

      openWorkspace: (input) => {
        const context = prepareWorkspaceContext(input.type, input.context ?? {})
        const key = contextDedupeKey(input.type, context)
        const existingId = findExistingTabId(
          get().tabs,
          get().dedupeIndex,
          get().activeTabId,
          input.type,
          context,
          key,
        )
        if (existingId) {
          const existing = get().tabs.find((t) => t.id === existingId)
          if (existing && isModuleHomeContext(input.type, context) && existing.context._home !== true) {
            get().patchTabContext(existingId, { _home: true })
          }
          get().activateTab(existingId)
          return existingId
        }

        const now = Date.now()
        const tab: WorkspaceTab = {
          id: uid(),
          type: input.type,
          title: buildWorkspaceTitle(input),
          module: WORKSPACE_TYPE_MODULE[input.type],
          context,
          investigationId: input.investigationId ?? context.investigationId,
          isPinned: Boolean(input.pin),
          isDirty: false,
          createdAt: now,
          lastActivatedAt: now,
        }

        set((s) => {
          const tabs = sortTabs([...s.tabs, tab])
          return {
            tabs,
            activeTabId: tab.id,
            dedupeIndex: rebuildIndex(tabs),
          }
        })
        return tab.id
      },

      openModuleHome: (module) => {
        const home = MODULE_HOME[module]
        return get().openWorkspace({
          type: home.type,
          title: home.title,
          context: home.context ?? {},
        })
      },

      activateTab: (id) => {
        set((s) => ({
          activeTabId: id,
          tabs: s.tabs.map((t) =>
            t.id === id ? { ...t, lastActivatedAt: Date.now() } : t
          ),
        }))
      },

      closeTab: (id) => {
        const tab = get().tabs.find((t) => t.id === id)
        if (!tab) return true
        if (tab.isPinned) return false
        if (tab.isDirty && tab.type === "actions") {
          const ok = window.confirm(
            `Fermer « ${tab.title} » ? Des modifications non enregistrées seront perdues.`
          )
          if (!ok) return false
        }

        set((s) => {
          const idx = s.tabs.findIndex((t) => t.id === id)
          const tabs = s.tabs.filter((t) => t.id !== id)
          const { [id]: _removed, ...tabState } = s.tabState
          let activeTabId = s.activeTabId
          if (activeTabId === id) {
            const neighbor = tabs[Math.min(idx, tabs.length - 1)] ?? tabs[0]
            activeTabId = neighbor?.id ?? null
          }
          return {
            tabs,
            activeTabId: ensureActive(tabs, activeTabId),
            tabState,
            dedupeIndex: rebuildIndex(tabs),
          }
        })
        return true
      },

      closeOthers: (id) => {
        set((s) => {
          const keep = s.tabs.filter((t) => t.id === id || t.isPinned)
          const tabState: TabStateMap = {}
          for (const t of keep) {
            if (s.tabState[t.id]) tabState[t.id] = s.tabState[t.id]
          }
          return {
            tabs: keep,
            activeTabId: id,
            tabState,
            dedupeIndex: rebuildIndex(keep),
          }
        })
      },

      closeToRight: (id) => {
        set((s) => {
          const idx = s.tabs.findIndex((t) => t.id === id)
          if (idx < 0) return s
          const tabs = s.tabs.filter((t, i) => i <= idx || t.isPinned)
          const tabState: TabStateMap = {}
          for (const t of tabs) {
            if (s.tabState[t.id]) tabState[t.id] = s.tabState[t.id]
          }
          return {
            tabs,
            activeTabId: ensureActive(tabs, s.activeTabId),
            tabState,
            dedupeIndex: rebuildIndex(tabs),
          }
        })
      },

      duplicateTab: (id) => {
        const src = get().tabs.find((t) => t.id === id)
        if (!src) return null
        const now = Date.now()
        const tab: WorkspaceTab = {
          ...src,
          id: uid(),
          title: `${src.title} (copie)`,
          isPinned: false,
          isDirty: false,
          createdAt: now,
          lastActivatedAt: now,
          // Force unique key by adding duplicate stamp in context
          context: { ...src.context, _dup: now },
        }
        set((s) => {
          const tabs = sortTabs([...s.tabs, tab])
          return {
            tabs,
            activeTabId: tab.id,
            tabState: {
              ...s.tabState,
              [tab.id]: { ...(s.tabState[src.id] ?? {}) },
            },
            dedupeIndex: rebuildIndex(tabs),
          }
        })
        return tab.id
      },

      pinTab: (id, pinned) => {
        set((s) => {
          const tabs = sortTabs(
            s.tabs.map((t) =>
              t.id === id ? { ...t, isPinned: pinned ?? !t.isPinned } : t
            )
          )
          return { tabs }
        })
      },

      reorderTabs: (fromIndex, toIndex) => {
        set((s) => {
          if (
            fromIndex < 0 ||
            toIndex < 0 ||
            fromIndex >= s.tabs.length ||
            toIndex >= s.tabs.length
          ) {
            return s
          }
          const tabs = [...s.tabs]
          const [item] = tabs.splice(fromIndex, 1)
          tabs.splice(toIndex, 0, item)
          return { tabs: sortTabs(tabs) }
        })
      },

      setTabDirty: (id, dirty) => {
        const tab = get().tabs.find((t) => t.id === id)
        if (!tab || tab.isDirty === dirty) return
        set((s) => ({
          tabs: s.tabs.map((t) => (t.id === id ? { ...t, isDirty: dirty } : t)),
        }))
      },

      setTabTitle: (id, title) => {
        const tab = get().tabs.find((t) => t.id === id)
        if (!tab || tab.title === title) return
        set((s) => ({
          tabs: s.tabs.map((t) => (t.id === id ? { ...t, title } : t)),
        }))
      },

      patchTabContext: (id, patch) => {
        set((s) => {
          const tabs = s.tabs.map((t) => {
            if (t.id !== id) return t
            const nextContext = { ...t.context, ...patch }
            if (isModuleHomeTab(t) || t.context._home === true) nextContext._home = true
            return { ...t, context: nextContext }
          })
          return { tabs, dedupeIndex: rebuildIndex(tabs) }
        })
      },

      setTabState: (id, partial) => {
        set((s) => ({
          tabState: {
            ...s.tabState,
            [id]: { ...(s.tabState[id] ?? {}), ...partial },
          },
        }))
      },

      getTabState: (id) => get().tabState[id] ?? {},

      nextTab: () => {
        const { tabs, activeTabId } = get()
        if (tabs.length === 0) return
        const idx = tabs.findIndex((t) => t.id === activeTabId)
        const next = tabs[(idx + 1) % tabs.length]
        if (next) get().activateTab(next.id)
      },

      prevTab: () => {
        const { tabs, activeTabId } = get()
        if (tabs.length === 0) return
        const idx = tabs.findIndex((t) => t.id === activeTabId)
        const prev = tabs[(idx - 1 + tabs.length) % tabs.length]
        if (prev) get().activateTab(prev.id)
      },

      activateByIndex: (index) => {
        const tab = get().tabs[index]
        if (tab) get().activateTab(tab.id)
      },
    }),
    {
      name: PERSIST_NAME,
      version: WORKSPACE_PERSIST_VERSION,
      storage: createJSONStorage(workspaceStorage),
      partialize: (s) => ({
        tabs: s.tabs,
        activeTabId: s.activeTabId,
        tabState: s.tabState,
        dedupeIndex: s.dedupeIndex,
      }),
      merge: (persisted, current) => {
        const snapshot = (persisted ?? {}) as PersistedWorkspace
        const hydrated = applyPersistedWorkspace(snapshot, current)
        return { ...current, ...hydrated }
      },
      migrate: (persisted) => persisted as PersistedWorkspace,
    }
  )
)

export function useActiveWorkspace() {
  const tabs = useWorkspaceStore((s) => s.tabs)
  const activeTabId = useWorkspaceStore((s) => s.activeTabId)
  return tabs.find((t) => t.id === activeTabId) ?? null
}

export function resetWorkspaceStore() {
  const tab: WorkspaceTab = {
    ...initialTab,
    createdAt: Date.now(),
    lastActivatedAt: Date.now(),
  }
  useWorkspaceStore.setState({
    tabs: [tab],
    activeTabId: tab.id,
    tabState: {},
    dedupeIndex: rebuildIndex([tab]),
  })
}

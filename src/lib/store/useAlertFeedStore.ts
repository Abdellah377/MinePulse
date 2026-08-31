import { create } from "zustand"

import { fetchActiveAlertCount, fetchAlertPage, type OpsContext } from "@/lib/api/client"
import type { Alert } from "@/lib/mock/types"

const MAX_FEED_IDS = 400

export type AlertFeedPage = {
  items: Alert[]
  nextCursor: string | null
  hasMore: boolean
  activeCount: number
}

type AlertFeedState = {
  orderedIds: string[]
  byId: Record<string, Alert>
  nextCursor: string | null
  hasMore: boolean
  activeCount: number
  loading: boolean
  loadingMore: boolean
  loaded: boolean
  siteCode: string | null
  reset: () => void
  setActiveCount: (count: number) => void
  upsert: (alert: Alert) => void
  mergeHead: (page: AlertFeedPage) => void
  appendPage: (page: AlertFeedPage) => void
  loadFirst: (ctx?: OpsContext) => Promise<void>
  loadMore: (ctx?: OpsContext) => Promise<void>
  refreshHead: (ctx?: OpsContext) => Promise<void>
}

function orderedAlerts(state: Pick<AlertFeedState, "orderedIds" | "byId">): Alert[] {
  return state.orderedIds.map((id) => state.byId[id]).filter((row): row is Alert => row != null)
}

function mergeRecords(existing: Record<string, Alert>, items: Alert[]): Record<string, Alert> {
  const next = { ...existing }
  for (const item of items) next[item.id] = item
  return next
}

function prependIds(current: string[], incoming: Alert[]): string[] {
  const seen = new Set(current)
  const fresh: string[] = []
  for (const item of incoming) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    fresh.push(item.id)
  }
  return [...fresh, ...current].slice(0, MAX_FEED_IDS)
}

function appendIds(current: string[], incoming: Alert[]): string[] {
  const seen = new Set(current)
  const next = [...current]
  for (const item of incoming) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    next.push(item.id)
  }
  return next.slice(0, MAX_FEED_IDS)
}

export const useAlertFeedStore = create<AlertFeedState>((set, get) => ({
  orderedIds: [],
  byId: {},
  nextCursor: null,
  hasMore: false,
  activeCount: 0,
  loading: false,
  loadingMore: false,
  loaded: false,
  siteCode: null,

  reset: () =>
    set({
      orderedIds: [],
      byId: {},
      nextCursor: null,
      hasMore: false,
      activeCount: 0,
      loading: false,
      loadingMore: false,
      loaded: false,
      siteCode: null,
    }),

  setActiveCount: (count) => set({ activeCount: count }),

  upsert: (alert) =>
    set((s) => ({
      byId: { ...s.byId, [alert.id]: alert },
      orderedIds: s.orderedIds.includes(alert.id) ? s.orderedIds : prependIds(s.orderedIds, [alert]),
    })),

  mergeHead: (page) =>
    set((s) => ({
      byId: mergeRecords(s.byId, page.items),
      orderedIds: prependIds(s.orderedIds, page.items),
      activeCount: page.activeCount,
      loaded: true,
      nextCursor: s.loaded ? s.nextCursor : page.nextCursor,
      hasMore: s.loaded ? s.hasMore : page.hasMore,
    })),

  appendPage: (page) =>
    set((s) => ({
      byId: mergeRecords(s.byId, page.items),
      orderedIds: appendIds(s.orderedIds, page.items),
      nextCursor: page.nextCursor,
      hasMore: page.hasMore,
      activeCount: page.activeCount,
      loaded: true,
    })),

  loadFirst: async (ctx) => {
    const siteCode = ctx?.siteCode ?? null
    if (get().loading) return
    set({ loading: true, siteCode })
    try {
      const page = await fetchAlertPage({ limit: 20 }, ctx)
      set({
        byId: mergeRecords({}, page.items),
        orderedIds: page.items.map((item) => item.id),
        nextCursor: page.nextCursor,
        hasMore: page.hasMore,
        activeCount: page.activeCount,
        loading: false,
        loaded: true,
        siteCode,
      })
    } catch {
      set({ loading: false })
      throw new Error("ALERT_FEED_LOAD_FAILED")
    }
  },

  loadMore: async (ctx) => {
    const state = get()
    if (!state.hasMore || !state.nextCursor || state.loadingMore) return
    set({ loadingMore: true })
    try {
      const page = await fetchAlertPage({ limit: 20, cursor: state.nextCursor }, ctx)
      get().appendPage(page)
      set({ loadingMore: false })
    } catch {
      set({ loadingMore: false })
      throw new Error("ALERT_FEED_LOAD_MORE_FAILED")
    }
  },

  refreshHead: async (ctx) => {
    try {
      const [page, count] = await Promise.all([
        fetchAlertPage({ limit: 20 }, ctx),
        fetchActiveAlertCount(ctx).catch(() => null),
      ])
      get().mergeHead(count ? { ...page, activeCount: count.activeCount } : page)
    } catch {
      // Poll failures stay in ops poll error handling.
    }
  },
}))

export function selectFeedAlerts(state: AlertFeedState): Alert[] {
  return orderedAlerts(state)
}

export function useVisibleAlerts(): Alert[] {
  const feedIds = useAlertFeedStore((s) => s.orderedIds)
  const byId = useAlertFeedStore((s) => s.byId)
  return feedIds.map((id) => byId[id]).filter((row): row is Alert => row != null)
}

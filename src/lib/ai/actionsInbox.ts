import type { ActionsInboxItem } from "@/lib/api/types/optimization"

export function mergeInboxItems(
  current: ActionsInboxItem[],
  incoming: ActionsInboxItem[],
  { prepend = false }: { prepend?: boolean } = {},
): ActionsInboxItem[] {
  const byId = new Map(current.map((item) => [item.id, item]))
  for (const item of incoming) byId.set(item.id, item)
  if (!prepend) {
    const seen = new Set<string>()
    const ordered: ActionsInboxItem[] = []
    for (const item of [...current, ...incoming]) {
      if (seen.has(item.id)) continue
      seen.add(item.id)
      ordered.push(byId.get(item.id)!)
    }
    return ordered
  }
  const seen = new Set<string>()
  const ordered: ActionsInboxItem[] = []
  for (const item of [...incoming, ...current]) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    ordered.push(byId.get(item.id)!)
  }
  return ordered
}

export function removeInboxItem(items: ActionsInboxItem[], id: string) {
  const remaining = items.filter((item) => item.id !== id)
  return { remaining, nextSelectedId: remaining[0]?.id ?? null }
}

export function pickInboxSelection(items: ActionsInboxItem[], preferredId?: string | null) {
  if (preferredId && items.some((item) => item.id === preferredId)) return preferredId
  return items[0]?.id ?? null
}

export function nextInboxSelection(
  items: ActionsInboxItem[],
  currentId: string | null | undefined,
  contextAlertId?: string | null,
  options?: { explicitContext?: boolean },
): string | null {
  const explicit = options?.explicitContext === true
  if (explicit && contextAlertId && items.some((item) => item.id === contextAlertId)) {
    return contextAlertId
  }
  if (currentId == null || currentId === "") {
    return pickInboxSelection(items, contextAlertId)
  }
  if (items.some((item) => item.id === currentId)) return currentId
  if (contextAlertId && items.some((item) => item.id === contextAlertId)) return contextAlertId
  return items[0]?.id ?? null
}

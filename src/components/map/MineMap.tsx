import { useEffect, useRef, useState, type ReactNode } from "react"
import { Map as MapLibreMap, type Map as MapLibreMapType } from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"

import { cn } from "@/lib/utils"
import {
  DEFAULT_BASEMAP,
  SITE_GEO,
  buildBasemapStyleUrl,
  hasMapTilerApiKey,
} from "@/features/map/map.constants"
import type { BasemapId } from "@/features/map/map.types"
import { registerEquipmentIcons } from "@/features/map/map.icons"
import { MineMapContext } from "@/components/map/MineMapContext"

interface MineMapProps {
  className?: string
  basemap?: BasemapId
  children?: ReactNode
  onReady?: (map: MapLibreMapType) => void
}

/**
 * MapLibre host — create once per mount. Change `basemap` via React `key` on the parent
 * to remount with a different style URL (provider-independent).
 */
export function MineMap({
  className,
  basemap = DEFAULT_BASEMAP,
  children,
  onReady,
}: MineMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMapType | null>(null)
  const [ready, setReady] = useState(false)
  const [mapInstance, setMapInstance] = useState<MapLibreMapType | null>(null)
  const [error, setError] = useState<string | null>(null)
  const onReadyRef = useRef(onReady)
  onReadyRef.current = onReady

  const styleUrl = buildBasemapStyleUrl(basemap)
  const hasKey = hasMapTilerApiKey()

  useEffect(() => {
    if (!hasKey || !styleUrl || !containerRef.current) return

    setError(null)
    setReady(false)

    let cancelled = false
    const container = containerRef.current

    const map = new MapLibreMap({
      container,
      style: styleUrl,
      center: SITE_GEO.center,
      zoom: SITE_GEO.zoom,
      minZoom: SITE_GEO.minZoom,
      maxZoom: SITE_GEO.maxZoom,
      bearing: SITE_GEO.bearing,
      pitch: SITE_GEO.pitch,
      attributionControl: { compact: true },
      // MapLibre's default is 3px: any mousedown→mouseup movement past that
      // means NO "click" event fires at all (independent of dragPan state).
      // Trackpad taps routinely drift more than 3px, which silently ate every
      // attempt to place a zone corner. Widen it so a tap reliably registers.
      clickTolerance: 8,
    })

    mapRef.current = map
    setMapInstance(map)

    let didFinish = false
    const finishReady = () => {
      if (cancelled || didFinish) return
      didFinish = true
      try {
        void registerEquipmentIcons(map).catch((e) => {
          console.warn("[MineMap] icon registration failed", e)
        })
      } catch (e) {
        console.warn("[MineMap] icon registration failed", e)
      }
      map.resize()
      setReady(true)
      onReadyRef.current?.(map)
    }

    const onLoad = () => finishReady()
    const onError = (e: { error?: Error; message?: string }) => {
      const msg = e.error?.message ?? e.message ?? "Erreur de chargement de la carte"
      // Ignore transient tile/font 404 noise once style is up
      if (map.isStyleLoaded()) return
      console.error("[MineMap]", e)
      setError(msg)
    }

    map.on("load", onLoad)
    map.on("error", onError)

    // Style may already be cached — `load` can fire before the listener is attached
    if (map.loaded()) finishReady()

    const ro = new ResizeObserver(() => {
      if (!cancelled && mapRef.current) mapRef.current.resize()
    })
    ro.observe(container)

    // Layout may not be final on first paint (flex parents)
    requestAnimationFrame(() => {
      if (!cancelled) map.resize()
    })

    return () => {
      cancelled = true
      ro.disconnect()
      map.off("load", onLoad)
      map.off("error", onError)
      map.remove()
      mapRef.current = null
      setReady(false)
      setMapInstance(null)
    }
  }, [hasKey, styleUrl])

  if (!hasKey) {
    return (
      <div
        className={cn(
          "flex h-full min-h-[240px] w-full flex-col items-center justify-center gap-2 bg-surface-2 px-6 text-center",
          className
        )}
      >
        <p className="text-sm font-semibold text-foreground">Carte indisponible</p>
        <p className="max-w-md text-xs leading-relaxed text-muted">
          Configurez{" "}
          <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[11px]">
            VITE_MAPTILER_API_KEY
          </code>{" "}
          dans <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[11px]">.env</code>,
          puis <strong>redémarrez</strong> le serveur (
          <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[11px]">npm run dev</code>
          ).
        </p>
      </div>
    )
  }

  return (
    <MineMapContext.Provider value={{ map: mapInstance, mapRef, ready }}>
      <div className={cn("relative h-full min-h-0 w-full", className)}>
        <div ref={containerRef} className="absolute inset-0 z-0 h-full w-full" />
        {error && (
          <div className="absolute inset-x-3 top-14 z-20 rounded-md border border-danger/30 bg-surface px-3 py-2 text-[11px] text-danger shadow-sm">
            Impossible de charger le fond de carte : {error}
          </div>
        )}
        {children}
      </div>
    </MineMapContext.Provider>
  )
}

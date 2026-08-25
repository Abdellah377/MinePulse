import {
  createContext,
  useContext,
  type MutableRefObject,
} from "react"
import type { Map as MapLibreMap } from "maplibre-gl"

export interface MineMapContextValue {
  map: MapLibreMap | null
  mapRef: MutableRefObject<MapLibreMap | null>
  ready: boolean
}

export const MineMapContext = createContext<MineMapContextValue>({
  map: null,
  mapRef: { current: null },
  ready: false,
})

export function useMineMap() {
  return useContext(MineMapContext)
}

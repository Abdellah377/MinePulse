import type { Map as MapLibreMap, StyleImageInterface } from "maplibre-gl"

import type { EquipmentType } from "@/lib/mock/types"
import { EQUIPMENT_ICON_SRC } from "@/lib/equipment-icons"
import { EQUIPMENT_ICON_IDS } from "@/features/map/map.constants"

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error(`Failed to load icon: ${url}`))
    img.src = url
  })
}

function makeMapIcon(img: HTMLImageElement, size = 96): StyleImageInterface {
  const canvas = document.createElement("canvas")
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext("2d")!
  ctx.clearRect(0, 0, size, size)

  // Transparent background — state halo on the map provides the contrast disc
  const pad = size * 0.06
  ctx.drawImage(img, pad, pad, size - pad * 2, size - pad * 2)

  const imageData = ctx.getImageData(0, 0, size, size)
  return {
    width: size,
    height: size,
    data: new Uint8Array(imageData.data.buffer),
  }
}

export async function registerEquipmentIcons(map: MapLibreMap) {
  const types = Object.keys(EQUIPMENT_ICON_IDS) as EquipmentType[]
  await Promise.all(
    types.map(async (type) => {
      const id = EQUIPMENT_ICON_IDS[type]
      const img = await loadImage(EQUIPMENT_ICON_SRC[type])
      const icon = makeMapIcon(img, 96)
      if (map.hasImage(id)) map.removeImage(id)
      map.addImage(id, icon, { pixelRatio: 2 })
    })
  )
}

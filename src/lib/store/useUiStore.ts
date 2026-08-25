import { create } from "zustand"

interface UiState {
  commandOpen: boolean
  equipmentDrawerId: string | null

  setCommandOpen: (open: boolean) => void
  openEquipmentDrawer: (id: string) => void
  closeEquipmentDrawer: () => void
}

export const useUiStore = create<UiState>((set) => ({
  commandOpen: false,
  equipmentDrawerId: null,

  setCommandOpen: (open) => set({ commandOpen: open }),
  openEquipmentDrawer: (id) => set({ equipmentDrawerId: id }),
  closeEquipmentDrawer: () => set({ equipmentDrawerId: null }),
}))

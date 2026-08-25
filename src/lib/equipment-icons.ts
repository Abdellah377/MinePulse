import type { EquipmentType } from "@/lib/mock/types"

import haulTruck from "@/assets/equipment/haul-truck.svg"
import excavator from "@/assets/equipment/excavator.svg"
import loader from "@/assets/equipment/loader.svg"
import dozer from "@/assets/equipment/dozer.svg"
import drill from "@/assets/equipment/drill.svg"
import grader from "@/assets/equipment/grader.svg"

/** Flat vector equipment icons — consistent style across UI + map. */
export const EQUIPMENT_ICON_SRC: Record<EquipmentType, string> = {
  haul_truck: haulTruck,
  excavator: excavator,
  loader: loader,
  dozer: dozer,
  drill: drill,
  grader: grader,
  water_truck: haulTruck,
  light_vehicle: haulTruck,
  other: grader,
}

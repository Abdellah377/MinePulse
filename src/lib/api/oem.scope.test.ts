import { expect, it, vi } from "vitest"
import { scopedOemApi } from "./oem"
import { fetchJson } from "./client"
vi.mock("./client", async (original) => ({ ...await original<typeof import("./client")>(), useApiMode: true, fetchJson: vi.fn().mockResolvedValue({ rows: [], points: [] }) }))

it("all OEM operational endpoints transport selected site and shift", async () => {
  const api = scopedOemApi({ siteCode: "REAL-SITE", shiftId: "shift-31" })
  await Promise.all([api.connectivity(), api.delays(30), api.pingFleet("UNIT-77"), api.telemetry("UNIT-77", "speed_kmh"), api.tyres("UNIT-77"), api.diagnostic({}), api.errors({}), api.maintenance({}), api.anomalies({})])
  for (const [path] of vi.mocked(fetchJson).mock.calls) {
    expect(path).toContain("site_code=REAL-SITE")
    expect(path).toContain("shift_id=shift-31")
  }
})

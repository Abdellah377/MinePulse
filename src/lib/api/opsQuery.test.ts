import { describe, expect, it } from "vitest"

import { opsQueryString } from "@/lib/api/client"

describe("opsQueryString", () => {
  it("encodes site and shift context", () => {
    const q = opsQueryString({ siteCode: "MP-SIM-01", shiftId: "shift-3" })
    expect(q).toBe("?site_code=MP-SIM-01&shift_id=shift-3")
  })

  it("appends extra params", () => {
    const q = opsQueryString({ siteCode: "MP-SIM-01" }, { lite: true })
    expect(q).toContain("site_code=MP-SIM-01")
    expect(q).toContain("lite=true")
  })

  it("returns empty string when no params", () => {
    expect(opsQueryString()).toBe("")
  })

  it("omits empty site and shift from query string", () => {
    expect(opsQueryString({ siteCode: "", shiftId: "" })).toBe("")
    expect(opsQueryString({ siteCode: "SITE-A", shiftId: "" })).toBe("?site_code=SITE-A")
  })

  it("appends analysis period and poste without a live shift id", () => {
    const q = opsQueryString({ siteCode: "MP-SIM-01" }, { from: "2026-01-28", to: "2026-01-30", poste: "nuit" })
    expect(q).toContain("site_code=MP-SIM-01")
    expect(q).toContain("from=2026-01-28")
    expect(q).toContain("to=2026-01-30")
    expect(q).toContain("poste=nuit")
    expect(q).not.toContain("shift_id")
  })
})

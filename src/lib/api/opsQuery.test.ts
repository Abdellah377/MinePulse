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
})

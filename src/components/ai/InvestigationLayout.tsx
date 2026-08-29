/** Original Alertes / Actions presentation primitives, shared by live and demo views. */
import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section>
    <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-2">{title}</h4>
    <div className="rounded-md border border-border bg-surface p-3">{children}</div>
  </section>
}

export function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return <div><dt className="text-muted-2">{label}</dt><dd className={cn("text-foreground/90", mono && "font-mono font-medium")}>{value}</dd></div>
}

export function AiBlock({ label, value, compact }: { label: string; value: string; compact?: boolean }) {
  return <div className="rounded-md border border-border bg-background px-3 py-2">
    <p className="text-[10px] font-semibold uppercase text-muted-2">{label}</p>
    <p className={cn("mt-0.5 text-[12px] text-foreground/90", compact && "line-clamp-2")}>{value}</p>
  </div>
}

export function Chip({ children }: { children: ReactNode }) {
  return <span className="inline-flex max-w-full truncate rounded-md bg-surface-2 px-2 py-1 text-[10px] text-muted">{children}</span>
}

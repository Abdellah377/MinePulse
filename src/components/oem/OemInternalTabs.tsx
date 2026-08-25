import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function OemInternalTabs<T extends string>({
  tabs,
  value,
  onChange,
  children,
}: {
  tabs: Array<{ id: T; label: string }>
  value: T
  onChange: (id: T) => void
  children: ReactNode
}) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="flex h-6 shrink-0 items-stretch border-b border-[#d0d5dc] bg-[#f3f5f7]">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            className={cn(
              "border-r border-[#d0d5dc] px-2.5 text-[11px] leading-[22px]",
              value === t.id ? "bg-white font-semibold text-[#222]" : "text-[#5f6b74] hover:bg-[#eef0f3]"
            )}
            onClick={() => onChange(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
    </div>
  )
}

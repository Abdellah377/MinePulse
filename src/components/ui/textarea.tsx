import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-16 w-full rounded-md border border-border-strong bg-surface-2 px-2.5 py-2 text-xs text-foreground outline-none transition-colors placeholder:text-muted-2 focus-visible:ring-1 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-40",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }

import { cn } from "@/lib/utils"
import ocpLogoColor from "@/assets/ocp_logo.png"
import ocpLogoHeader from "@/assets/ocp_logo_header.png"

interface OcpLogoProps {
  className?: string
  /**
   * header — white mark for the green brand top bar
   * color — branded green mark (for light surfaces / splash)
   */
  variant?: "header" | "color"
  title?: string
}

export function OcpLogo({
  className,
  variant = "header",
  title = "OCP",
}: OcpLogoProps) {
  if (variant === "header") {
    return (
      <img
        src={ocpLogoHeader}
        alt={title}
        title={title}
        className={cn(
          "shrink-0 object-contain object-center",
          /* PNG is green-on-black → white mark on brand green header */
          "brightness-0 invert",
          className
        )}
        draggable={false}
      />
    )
  }

  return (
    <img
      src={ocpLogoColor}
      alt={title}
      title={title}
      className={cn("shrink-0 object-contain object-center", className)}
      draggable={false}
    />
  )
}

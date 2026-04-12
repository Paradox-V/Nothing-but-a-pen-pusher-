import { cn } from "@/lib/utils"

interface EmptyProps {
  icon: React.ReactNode
  title: string
  description?: string
  className?: string
}

export function Empty({ icon, title, description, className }: EmptyProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-20 gap-3", className)}>
      <div className="text-muted-foreground/40">{icon}</div>
      <p className="text-[15px] text-muted-foreground font-medium">{title}</p>
      {description && (
        <p className="text-[13px] text-muted-foreground/60">{description}</p>
      )}
    </div>
  )
}

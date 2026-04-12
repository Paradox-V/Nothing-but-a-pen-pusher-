import { Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface LoadingProps {
  className?: string
  text?: string
}

export function Loading({ className, text = "加载中" }: LoadingProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-20 gap-3", className)}>
      <Loader2 className="animate-spin text-muted-foreground/40" size={24} />
      <p className="text-[13px] text-muted-foreground">{text}</p>
    </div>
  )
}

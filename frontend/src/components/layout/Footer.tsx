import { ExternalLink } from "lucide-react"
import { useTheme } from "@/hooks/use-theme"

export function Footer() {
  const { theme } = useTheme()
  const v = theme === "vintage"

  return (
    <footer className={v ? "py-12 px-6 border-t border-[#4F7942]/15" : "py-12 px-6 border-t border-border"}>
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        <p className={v ? "text-[13px] text-[#4F7942]/50" : "text-[13px] text-muted-foreground"}>
          信源汇总 · AI 驱动的智能信息中枢
        </p>
        <div className="flex items-center gap-4">
          <a
            href="https://github.com/wheelermarion1-dot/Nothing-but-a-pen-pusher-"
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ExternalLink size={16} />
          </a>
        </div>
      </div>
    </footer>
  )
}

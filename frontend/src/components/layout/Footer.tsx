import { ExternalLink } from "lucide-react"

export function Footer() {
  return (
    <footer className="py-12 px-6 border-t border-border">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        <p className="text-[13px] text-muted-foreground">
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

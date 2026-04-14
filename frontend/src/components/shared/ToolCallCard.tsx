import { useState } from "react"

interface ToolCallCardProps {
  tool: string
  args: Record<string, unknown>
  summary?: string
}

const TOOL_ICONS: Record<string, string> = {
  search_news_semantic: "🔍",
  search_multi_source: "🔎",
  get_news_categories: "📂",
  get_latest_news: "📰",
  get_hotlist_rankings: "🔥",
  get_trending_overview: "📊",
}

const TOOL_NAMES: Record<string, string> = {
  search_news_semantic: "新闻搜索",
  search_multi_source: "多源搜索",
  get_news_categories: "分类查询",
  get_latest_news: "最新新闻",
  get_hotlist_rankings: "热榜排行",
  get_trending_overview: "热点概览",
}

export default function ToolCallCard({ tool, args, summary }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const icon = TOOL_ICONS[tool] || "🔧"
  const name = TOOL_NAMES[tool] || tool
  const queryArg = args.query || args.keyword || ""

  return (
    <div
      className="my-1 rounded-lg border border-border/50 bg-muted/30 text-sm cursor-pointer hover:bg-muted/50 transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-2 px-3 py-1.5">
        <span>{icon}</span>
        <span className="font-medium text-muted-foreground">{name}</span>
        {queryArg && (
          <span className="text-muted-foreground truncate">
            "{String(queryArg)}"
          </span>
        )}
        {summary && (
          <>
            <span className="text-muted-foreground">→</span>
            <span className="text-muted-foreground truncate">{summary}</span>
          </>
        )}
      </div>
      {expanded && (
        <div className="px-3 pb-2 text-xs text-muted-foreground border-t border-border/30">
          <pre className="mt-1 whitespace-pre-wrap">
            {JSON.stringify(args, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

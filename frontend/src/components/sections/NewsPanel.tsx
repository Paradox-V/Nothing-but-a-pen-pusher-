import { useState, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Search, RefreshCw, ExternalLink, Sparkles, Filter, Newspaper } from "lucide-react"
import { cn } from "@/lib/utils"
import { Loading } from "@/components/shared/Loading"
import { Empty } from "@/components/shared/Empty"
import { AnimateIn } from "@/components/shared/AnimateIn"

import { apiFetch } from "@/hooks/use-api"

interface NewsItem {
  id: number
  title: string
  content: string
  source: string
  url: string
  published_at: string
  category: string
  tags: string[]
  similarity?: number
}

interface Category {
  category: string
  count: number
}

// 后端 _row_to_dict 返回 source_name / created_at / category:list，统一映射
function normalizeItem(raw: Record<string, unknown>): NewsItem {
  const category = raw.category
  let cat = "其他"
  if (Array.isArray(category)) cat = category[0] || "其他"
  else if (typeof category === "string") cat = category
  return {
    id: raw.id as number,
    title: (raw.title as string) || "",
    content: (raw.content as string) || "",
    source: (raw.source_name as string) || "",
    url: (raw.url as string) || "",
    published_at: (raw.created_at as string) || (raw.timestamp as string) || "",
    category: cat,
    tags: Array.isArray(raw.tags) ? raw.tags as string[] : [],
    similarity: raw.similarity as number | undefined,
  }
}

export function NewsPanel() {
  const [news, setNews] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [keyword, setKeyword] = useState("")
  const [semantic, setSemantic] = useState(false)
  const [categories, setCategories] = useState<Category[]>([])
  const [sources, setSources] = useState<string[]>([])
  const [activeCategories, setActiveCategories] = useState<string[]>([])
  const [activeSources, setActiveSources] = useState<string[]>([])
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const perPage = 20

  const fetchNews = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(page), per_page: String(perPage) })
      if (keyword) params.set(semantic ? "q" : "keyword", keyword)
      if (semantic && keyword) {
        params.set("n", String(perPage))
        // 后端用逗号分隔，不用 append
        if (activeCategories.length > 0) params.set("categories", activeCategories.join(","))
        if (activeSources.length > 0) params.set("sources", activeSources.join(","))
      } else {
        if (activeCategories.length > 0) params.set("categories", activeCategories.join(","))
        if (activeSources.length > 0) params.set("sources", activeSources.join(","))
      }

      const endpoint = semantic && keyword ? "/news/semantic_search" : "/news"
      const res = await apiFetch(`${endpoint}?${params}`)
      const data = await res.json()

      if (semantic && keyword) {
        // 语义搜索返回 results 数组
        const rawResults = Array.isArray(data) ? data : (data.results || [])
        setNews(rawResults.map(normalizeItem))
        setTotal(rawResults.length)
      } else {
        const rawItems = data.items || []
        setNews(rawItems.map(normalizeItem))
        setTotal(data.total || 0)
      }
    } catch (err) {
      console.error("Failed to fetch news:", err)
    } finally {
      setLoading(false)
    }
  }, [page, keyword, semantic, activeCategories, activeSources])

  useEffect(() => { fetchNews() }, [fetchNews])

  useEffect(() => {
    // 后端 /api/news/categories 返回 [{category, count}]
    apiFetch("/news/categories").then((r) => r.json()).then(setCategories).catch(() => {})
    // 后端 /api/news/status 返回 { sources: string[], source_stats: {...} }
    apiFetch("/news/status").then((r) => r.json()).then((d) => setSources(d.sources || [])).catch(() => {})
  }, [])

  const toggleCategory = (c: string) =>
    setActiveCategories((prev) => prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c])
  const toggleSource = (s: string) =>
    setActiveSources((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s])

  const handleRefresh = async () => {
    await apiFetch("/news/fetch", { method: "POST" }).catch(() => {})
    fetchNews()
  }

  const totalPages = Math.ceil(total / perPage)

  const getPageNumbers = (current: number, total: number): (number | string)[] => {
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
    const pages: (number | string)[] = [1]
    if (current > 3) pages.push("...")
    const start = Math.max(2, current - 1)
    const end = Math.min(total - 1, current + 1)
    for (let i = start; i <= end; i++) pages.push(i)
    if (current < total - 2) pages.push("...")
    pages.push(total)
    return pages
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <AnimateIn>
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-foreground/25" />
            <input
              type="text"
              placeholder={semantic ? "输入语义搜索查询..." : "搜索新闻..."}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && setPage(1)}
              className="w-full pl-11 pr-4 py-2.5 bg-muted border border-border rounded-xl text-[14px] text-foreground placeholder:text-foreground/25 focus:outline-none focus:border-accent/30 transition-colors"
            />
          </div>
          <button
            onClick={() => setSemantic(!semantic)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2.5 rounded-xl text-[13px] font-medium border transition-all",
              semantic
                ? "bg-accent/10 border-accent/20 text-accent"
                : "bg-accent/8 border-accent/15 text-accent/60 hover:text-accent"
            )}
          >
            <Sparkles size={14} />
            语义
          </button>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={cn("p-2.5 rounded-xl border transition-all",
              showFilters ? "bg-accent border-accent text-accent-foreground" : "bg-muted border-border text-muted-foreground hover:text-foreground"
            )}
          >
            <Filter size={16} />
          </button>
          <button
            onClick={handleRefresh}
            className={cn("p-2.5 rounded-xl border transition-all",
              "bg-muted border-border text-muted-foreground hover:text-foreground"
            )}
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </AnimateIn>

      <AnimatePresence>
        {showFilters && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3 }} className="overflow-hidden mb-6">
            <div className="space-y-3">
              {categories.length > 0 && (
                <div>
                  <p className="text-[11px] text-foreground/30 uppercase tracking-wider mb-2">分类</p>
                  <div className="flex flex-wrap gap-1.5">
                    {categories.map((c) => (
                      <button key={c.category} onClick={() => toggleCategory(c.category)}
                        className={cn("px-3 py-1 rounded-full text-[12px] font-medium border transition-all",
                          activeCategories.includes(c.category) ? "bg-muted border-border text-foreground" : "bg-transparent border-border text-muted-foreground hover:text-foreground"
                        )}
                      >
                        {c.category} <span className="ml-1 text-muted-foreground/60">{c.count}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {sources.length > 0 && (
                <div>
                  <p className="text-[11px] text-foreground/30 uppercase tracking-wider mb-2">来源</p>
                  <div className="flex flex-wrap gap-1.5">
                    {sources.map((s) => (
                      <button key={s} onClick={() => toggleSource(s)}
                        className={cn("px-3 py-1 rounded-full text-[12px] font-medium border transition-all",
                          activeSources.includes(s) ? "bg-muted border-border text-foreground" : "bg-transparent border-border text-muted-foreground hover:text-foreground"
                        )}
                      >{s}</button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {loading ? (
        <Loading />
      ) : news.length === 0 ? (
        <Empty icon={<Newspaper size={40} />} title="暂无新闻" description="尝试调整搜索或筛选条件" />
      ) : (
        <motion.div layout className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <AnimatePresence mode="popLayout">
            {news.map((item, i) => (
              <motion.article
                key={item.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ delay: i * 0.03, duration: 0.3 }}
                onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
                className="group relative rounded-2xl bg-card border border-border p-5 cursor-pointer hover:border-foreground/10 transition-all duration-300"
              >
                <div className="flex items-center gap-2 mb-3">
                  <span className="px-2 py-0.5 rounded-md bg-muted text-[11px] text-muted-foreground font-medium">{item.source}</span>
                  {item.category && <span className="px-2 py-0.5 rounded-md bg-accent/10 text-[11px] text-accent font-medium">{item.category}</span>}
                  {item.similarity != null && <span className="px-2 py-0.5 rounded-md bg-[#5e5ce6]/10 text-[11px] text-[#5e5ce6]/70 font-medium tabular-nums">{Math.round(item.similarity * 100)}%</span>}
                  <span className="ml-auto text-[11px] text-muted-foreground/60 tabular-nums">{new Date(item.published_at).toLocaleDateString("zh-CN")}</span>
                </div>
                <h3 className="text-[15px] font-semibold tracking-tight text-foreground mb-2 line-clamp-2 group-hover:text-foreground transition-colors">{item.title}</h3>
                <p className={cn("text-[13px] leading-relaxed text-muted-foreground transition-all", expandedId === item.id ? "line-clamp-none" : "line-clamp-2")}>{item.content}</p>
                {item.tags?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-3">
                    {item.tags.slice(0, 5).map((tag) => <span key={tag} className="text-[11px] text-muted-foreground/60">#{tag}</span>)}
                  </div>
                )}
                {expandedId === item.id && item.url && (
                  <motion.a initial={{ opacity: 0 }} animate={{ opacity: 1 }} href={item.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center gap-1 mt-3 text-[12px] text-accent hover:text-accent/80 transition-colors"
                  >查看原文 <ExternalLink size={11} /></motion.a>
                )}
              </motion.article>
            ))}
          </AnimatePresence>
        </motion.div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-8">
          <button
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            className={cn("px-3 h-8 rounded-lg text-[13px] transition-all disabled:opacity-30",
              "text-accent hover:text-accent/80 hover:bg-accent/8"
            )}
          >上一页</button>
          {getPageNumbers(page, totalPages).map((p, i) =>
            typeof p === "string" ? (
              <span key={`ellipsis-${i}`} className="w-8 h-8 flex items-center justify-center text-[13px] text-muted-foreground">...</span>
            ) : (
              <button key={p} onClick={() => setPage(p)}
                className={cn("w-8 h-8 rounded-lg text-[13px] font-medium transition-all",
                  p === page
                    ? "bg-accent/15 text-accent"
                    : "text-accent/40 hover:text-accent/70 hover:bg-accent/8"
                )}
              >{p}</button>
            )
          )}
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(page + 1)}
            className={cn("px-3 h-8 rounded-lg text-[13px] transition-all disabled:opacity-30",
              "text-accent hover:text-accent/80 hover:bg-accent/8"
            )}
          >下一页</button>
        </div>
      )}
    </div>
  )
}

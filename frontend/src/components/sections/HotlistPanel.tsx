import { useState, useEffect, useCallback, useRef } from "react"
import { motion } from "framer-motion"
import { RefreshCw, TrendingUp, ExternalLink, Flame, AlertCircle, Clock } from "lucide-react"
import { cn } from "@/lib/utils"
import { Loading } from "@/components/shared/Loading"
import { Dropdown } from "@/components/shared/Dropdown"
import { Empty } from "@/components/shared/Empty"
import { AnimateIn } from "@/components/shared/AnimateIn"
import { useTheme } from "@/hooks/use-theme"
import { apiFetch } from "@/hooks/use-api"

interface HotItem {
  id: number
  title: string
  platform: string
  platform_name: string
  url: string
  hot_score: number
  hot_rank: number
  appear_count: number
  crawl_time: string
}

interface PlatformStat {
  platform: string
  platform_name: string
  count: number
  latest: string
}

type FetchState = "idle" | "fetching" | "success" | "failed"

const RANK_COLORS_DARK = ["text-[#ff375f]", "text-[#ff9f0a]", "text-[#30d158]"]
const RANK_COLORS_VINTAGE = ["text-[#A84860]", "text-[#B8862D]", "text-accent"]

// 平台ID -> 中文名 的后备映射
const PLATFORM_FALLBACK: Record<string, string> = {
  weibo: "微博", zhihu: "知乎", "bilibili-hot-search": "B站热搜",
  toutiao: "今日头条", baidu: "百度热搜", "wallstreetcn-hot": "华尔街见闻",
  thepaper: "澎湃新闻", "cls-hot": "财联社热门", ifeng: "凤凰网",
  douyin: "抖音", tieba: "贴吧",
}

export function HotlistPanel() {
  const [items, setItems] = useState<HotItem[]>([])
  const [loading, setLoading] = useState(true)
  const [platform, setPlatform] = useState("")
  const [hours, setHours] = useState(24)
  const [platforms, setPlatforms] = useState<PlatformStat[]>([])
  const [fetchState, setFetchState] = useState<FetchState>("idle")
  const [fetchMsg, setFetchMsg] = useState("")
  const [lastCrawlTime, setLastCrawlTime] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const { theme } = useTheme()

  const fetchHotlist = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ hours: String(hours), page: "1", page_size: "50" })
      if (platform) params.set("platform", platform)
      const res = await apiFetch(`/hotlist?${params}`)
      if (!res.ok) throw new Error(`请求失败: ${res.status}`)
      const data = await res.json()
      setItems(data.items || [])
    } catch (e) {
      setItems([])
      setError("热榜数据加载失败，请稍后重试")
    } finally { setLoading(false) }
  }, [platform, hours])

  const fetchPlatforms = useCallback(async () => {
    try {
      const res = await apiFetch("/hotlist/platforms")
      if (!res.ok) throw new Error("获取平台列表失败")
      const data = await res.json()
      if (Array.isArray(data)) setPlatforms(data)
    } catch { /* platforms 不是关键，静默 */ }
  }, [])

  const fetchStatus = useCallback(async () => {
    try {
      const res = await apiFetch("/hotlist/status")
      if (res.ok) {
        const data = await res.json()
        setLastCrawlTime(data.last_crawl_time)
      }
    } catch { /* */ }
  }, [])

  useEffect(() => { fetchPlatforms(); fetchStatus() }, [fetchPlatforms, fetchStatus])
  useEffect(() => { fetchHotlist() }, [fetchHotlist])

  const handleRefresh = async () => {
    setFetchState("fetching")
    setFetchMsg("正在抓取热榜...")
    setError(null)

    try {
      const res = await apiFetch("/hotlist/fetch", { method: "POST" })
      const data = await res.json()

      if (data.mode === "sync" && data.status === "completed") {
        // 同步抓取完成
        setFetchState("success")
        setFetchMsg("热榜已更新")
        await fetchHotlist()
        await fetchStatus()
        setTimeout(() => setFetchState("idle"), 3000)
      } else if (data.mode === "sync" && data.status === "failed") {
        setFetchState("failed")
        setFetchMsg(data.message || "热榜抓取失败")
      } else if (data.mode === "async" || data.status === "pending") {
        // 异步模式：轮询等待
        setFetchMsg("已触发抓取，等待处理...")
        let attempts = 0
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(async () => {
          attempts++
          try {
            const sr = await apiFetch("/hotlist/fetch_status")
            const sd = await sr.json()
            if (sd.status === "idle" || attempts >= 30) {
              if (pollRef.current) clearInterval(pollRef.current)
              if (attempts >= 30) {
                setFetchState("failed")
                setFetchMsg("抓取超时，scheduler 可能未启动")
              } else {
                setFetchState("success")
                setFetchMsg("热榜已更新")
                await fetchHotlist()
                await fetchStatus()
              }
              setTimeout(() => setFetchState("idle"), 3000)
            }
          } catch {
            if (pollRef.current) clearInterval(pollRef.current)
            setFetchState("failed")
            setFetchMsg("状态查询失败")
          }
        }, 2000)
      }
    } catch {
      setFetchState("failed")
      setFetchMsg("网络请求失败，请检查服务是否启动")
    }
  }

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const rankColors = theme === "vintage" ? RANK_COLORS_VINTAGE : RANK_COLORS_DARK

  const getPlatformName = (item: HotItem) =>
    item.platform_name || PLATFORM_FALLBACK[item.platform] || item.platform

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <AnimateIn>
        <div className="flex items-center gap-3 mb-6 flex-wrap">
          <Dropdown value={platform} onChange={setPlatform} placeholder="全部平台" minWidth={130}
            options={[{ value: "", label: "全部平台" }, ...platforms.map((p) => ({ value: p.platform, label: p.platform_name }))]}
          />
          <Dropdown value={String(hours)} onChange={(v) => setHours(Number(v))} placeholder="24 小时" minWidth={100}
            options={[6,12,24,48,72].map((h) => ({ value: String(h), label: `${h} 小时` }))}
          />
          <div className="ml-auto flex items-center gap-2">
            {lastCrawlTime && (
              <span className="text-[11px] text-muted-foreground/60 flex items-center gap-1">
                <Clock size={10} />
                {new Date(lastCrawlTime).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
            <button onClick={handleRefresh} disabled={fetchState === "fetching"}
              className={cn("p-2.5 rounded-xl border transition-all disabled:opacity-50",
                "bg-muted border-border text-muted-foreground hover:text-foreground"
              )}
            ><RefreshCw size={16} className={cn(fetchState === "fetching" && "animate-spin")} /></button>
          </div>
        </div>
      </AnimateIn>

      {/* 刷新状态反馈 */}
      {fetchState !== "idle" && (
        <AnimateIn>
          <div className={cn("mb-4 px-4 py-2.5 rounded-xl text-[13px] flex items-center gap-2",
            fetchState === "fetching" ? "bg-accent/10 text-accent" :
            fetchState === "success" ? "bg-[#30d158]/10 text-[#30d158]" :
            "bg-destructive/10 text-destructive"
          )}>
            {fetchState === "fetching" && <RefreshCw size={13} className="animate-spin" />}
            {fetchState === "success" && <span>✓</span>}
            {fetchState === "failed" && <AlertCircle size={13} />}
            {fetchMsg}
          </div>
        </AnimateIn>
      )}

      {error && (
        <AnimateIn>
          <div className="mb-4 px-4 py-2.5 rounded-xl bg-destructive/10 text-destructive text-[13px] flex items-center gap-2">
            <AlertCircle size={13} /> {error}
          </div>
        </AnimateIn>
      )}

      {loading ? <Loading /> : items.length === 0 ? (
        <Empty icon={<TrendingUp size={40} />} title="暂无热榜数据" description={fetchState === "failed" ? "抓取失败，请重试" : "点击刷新获取最新热榜"} />
      ) : (
        <div className="space-y-2">
          {items.map((item, i) => (
            <motion.div key={item.id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.02, duration: 0.3 }}
              className="group flex items-center gap-4 p-4 rounded-2xl bg-card border border-border hover:border-foreground/10 transition-all"
            >
              <span className={cn("w-8 text-center text-[18px] font-bold tabular-nums",
                i < 3 ? rankColors[i] : "text-muted-foreground/30"
              )}>{item.hot_rank || (i + 1)}</span>
              <div className="flex-1 min-w-0">
                <h3 className="text-[14px] font-medium text-foreground/90 truncate group-hover:text-foreground transition-colors">{item.title}</h3>
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-[11px] text-muted-foreground">{getPlatformName(item)}</span>
                  {item.appear_count > 1 && (
                    <span className="text-[11px] text-accent/60 flex items-center gap-1"><Flame size={10} /> {item.appear_count}次上榜</span>
                  )}
                </div>
              </div>
              {item.hot_score > 0 && (
                <span className="text-[13px] font-semibold text-muted-foreground tabular-nums">
                  {item.hot_score >= 10000 ? `${(item.hot_score / 10000).toFixed(1)}万` : item.hot_score}
                </span>
              )}
              {item.url && (
                <a href={item.url} target="_blank" rel="noopener noreferrer" className="p-2 rounded-lg text-muted-foreground/50 hover:text-foreground transition-colors">
                  <ExternalLink size={14} />
                </a>
              )}
            </motion.div>
          ))}
        </div>
      )}
    </div>
  )
}

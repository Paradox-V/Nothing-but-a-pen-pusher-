import { useState, useEffect, useCallback, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Search, RefreshCw, Rss, ExternalLink, Plus, Settings2, X, Compass, Code, Edit3, Check, AlertCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { Loading } from "@/components/shared/Loading"
import { Dropdown } from "@/components/shared/Dropdown"
import { Empty } from "@/components/shared/Empty"
import { AnimateIn } from "@/components/shared/AnimateIn"

import { apiFetch } from "@/hooks/use-api"

interface RssItem { id: number; title: string; summary: string; url: string; feed_name: string; published_at: string }
interface Feed { id: string; name: string; url: string; enabled: boolean; last_crawl_time: string | null; last_error: string | null; format?: string; status?: string; message?: string }

export function RssPanel() {
  const [items, setItems] = useState<RssItem[]>([])
  const [feeds, setFeeds] = useState<Feed[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedFeed, setSelectedFeed] = useState<string>("")
  const [keyword, setKeyword] = useState("")
  const [page, setPage] = useState(1)
  const [showManager, setShowManager] = useState(false)
  const [newFeedName, setNewFeedName] = useState("")
  const [newFeedUrl, setNewFeedUrl] = useState("")
  const [toast, setToast] = useState<string | null>(null)
  const perPage = 20

  // 发现功能
  const [showDiscover, setShowDiscover] = useState(false)
  const [discoverUrl, setDiscoverUrl] = useState("")
  const [discoverResults, setDiscoverResults] = useState<{ name: string; url: string }[]>([])
  const [discoverLoading, setDiscoverLoading] = useState(false)

  // 自定义 CSS 发现
  const [showCustomDiscover, setShowCustomDiscover] = useState(false)
  const [customUrl, setCustomUrl] = useState("")
  const [customItemSelector, setCustomItemSelector] = useState("")
  const [customTitleSelector, setCustomTitleSelector] = useState("")
  const [customLoading, setCustomLoading] = useState(false)
  const [customResult, setCustomResult] = useState<string | null>(null)

  // 编辑源
  const [editingFeed, setEditingFeed] = useState<Feed | null>(null)
  const [editName, setEditName] = useState("")
  const [editUrl, setEditUrl] = useState("")
  const toastRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 微信公众号 RSS 发现
  const [showWechatDiscover, setShowWechatDiscover] = useState(false)
  const [wechatUrl, setWechatUrl] = useState("")
  const [wechatLoading, setWechatLoading] = useState(false)
  const [wechatResult, setWechatResult] = useState<{ name: string; feed_url: string; warning?: string } | null>(null)

  // AI 话题搜索
  const [showAiSearch, setShowAiSearch] = useState(false)
  const [aiSearchTopic, setAiSearchTopic] = useState("")
  const [aiSearchLoading, setAiSearchLoading] = useState(false)
  const [aiSearchResults, setAiSearchResults] = useState<{ name: string; feed_url: string; verified: boolean; subscribers: number }[]>([])

  const showToast = (msg: string) => {
    if (toastRef.current) clearTimeout(toastRef.current)
    setToast(msg)
    toastRef.current = setTimeout(() => setToast(null), 3000)
  }

  useEffect(() => {
    return () => { if (toastRef.current) clearTimeout(toastRef.current) }
  }, [])

  const fetchRss = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(perPage) })
      if (selectedFeed) params.set("feed_id", String(selectedFeed))
      if (keyword) params.set("keyword", keyword)
      const res = await apiFetch(`/rss/items?${params}`)
      const data = await res.json()
      setItems(data.items || [])
    } catch { setItems([]) } finally { setLoading(false) }
  }, [page, selectedFeed, keyword])

  useEffect(() => { apiFetch("/rss/feeds").then((r) => r.json()).then(setFeeds).catch(() => {}) }, [])
  useEffect(() => { fetchRss() }, [fetchRss])

  const addFeed = async () => {
    if (!newFeedName || !newFeedUrl) return
    try {
      const res = await apiFetch("/rss/feeds", { method: "POST", body: JSON.stringify({ name: newFeedName, url: newFeedUrl }) })
      const data = await res.json()
      if (!res.ok || data.success === false) { showToast(data.error || "添加失败"); return }
      // 首次添加后验证抓取
      showToast("已添加，首次抓取将在下次调度周期执行")
      setNewFeedName(""); setNewFeedUrl("")
      const feedsRes = await apiFetch("/rss/feeds")
      setFeeds(await feedsRes.json())
    } catch { showToast("网络错误") }
  }

  const toggleFeed = async (feed: Feed) => {
    const res = await apiFetch(`/rss/feeds/${feed.id}`, { method: "PUT", body: JSON.stringify({ enabled: !feed.enabled }) })
    const data = await res.json()
    if (res.ok && data.success) {
      setFeeds((prev) => prev.map((f) => f.id === feed.id ? { ...f, enabled: !feed.enabled } : f))
    }
  }

  const deleteFeed = async (id: string) => {
    await apiFetch(`/rss/feeds/${id}`, { method: "DELETE" })
    setFeeds((prev) => prev.filter((f) => f.id !== id))
  }

  const saveEditFeed = async () => {
    if (!editingFeed) return
    const res = await apiFetch(`/rss/feeds/${editingFeed.id}`, {
      method: "PUT",
      body: JSON.stringify({ name: editName, url: editUrl }),
    })
    const data = await res.json()
    if (res.ok && data.success) {
      setFeeds((prev) => prev.map((f) => f.id === editingFeed.id ? { ...f, name: editName, url: editUrl } : f))
      setEditingFeed(null)
      showToast("已保存")
    } else {
      showToast(data.error || "保存失败")
    }
  }

  // 后端 discover 返回 {success, site_name, routes: [{name, feed_url, sample_items, item_count}]}
  const discoverFeed = async () => {
    if (!discoverUrl) return
    setDiscoverLoading(true)
    try {
      const res = await apiFetch("/rss/discover", { method: "POST", body: JSON.stringify({ url: discoverUrl }) })
      const data = await res.json()
      if (data.success && data.routes) {
        // routes 里的每一项: {name, feed_url, sample_items, item_count}
        setDiscoverResults(data.routes.map((r: { name: string; feed_url: string }) => ({ name: r.name, url: r.feed_url })))
      } else {
        showToast(data.error || "未发现可用订阅源")
        setDiscoverResults([])
      }
    } catch { showToast("发现失败") } finally { setDiscoverLoading(false) }
  }

  // 后端 custom discover 也返回 {success, routes: [{feed_url}]}
  const customDiscoverFeed = async () => {
    if (!customUrl || !customItemSelector) return
    setCustomLoading(true)
    try {
      const res = await apiFetch("/rss/discover/custom", { method: "POST", body: JSON.stringify({ url: customUrl, item_selector: customItemSelector, title_selector: customTitleSelector || undefined }) })
      const data = await res.json()
      if (data.success && data.routes?.[0]?.feed_url) {
        setCustomResult(data.routes[0].feed_url)
        showToast("RSS 源已生成")
      } else {
        showToast(data.error || "生成失败")
        setCustomResult(null)
      }
    } catch { showToast("生成失败") } finally { setCustomLoading(false) }
  }

  const discoverWechat = async () => {
    if (!wechatUrl) return
    setWechatLoading(true)
    setWechatResult(null)
    try {
      const res = await apiFetch("/rss/discover/wechat", { method: "POST", body: JSON.stringify({ url: wechatUrl }) })
      const data = await res.json()
      if (data.success) {
        setWechatResult({ name: data.name, feed_url: data.feed_url, warning: data.warning })
      } else {
        showToast(data.error || "转换失败")
      }
    } catch { showToast("转换失败") } finally { setWechatLoading(false) }
  }

  const searchAiRss = async () => {
    if (!aiSearchTopic) return
    setAiSearchLoading(true)
    setAiSearchResults([])
    try {
      const res = await apiFetch("/rss/search", { method: "POST", body: JSON.stringify({ topic: aiSearchTopic, max_results: 8 }) })
      const data = await res.json()
      if (data.success) {
        setAiSearchResults(data.results || [])
      } else {
        showToast(data.error || "搜索失败")
      }
    } catch { showToast("搜索失败") } finally { setAiSearchLoading(false) }
  }

  const bulkSubscribeAi = async () => {
    const validFeeds = aiSearchResults.filter(r => r.verified)
    if (!validFeeds.length) { showToast("没有有效的 RSS 源"); return }
    try {
      const res = await apiFetch("/rss/bulk-subscribe", {
        method: "POST",
        body: JSON.stringify({ feeds: validFeeds.map(r => ({ name: r.name, url: r.feed_url })) }),
      })
      const data = await res.json()
      showToast(`已订阅 ${data.success} 个，失败 ${data.failed} 个`)
      const feedsRes = await apiFetch("/rss/feeds")
      setFeeds(await feedsRes.json())
      setShowDiscover(false)
    } catch { showToast("批量订阅失败") }
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div initial={{ opacity: 0, y: -20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}
            className="fixed top-4 right-4 z-[100] px-4 py-2.5 rounded-xl bg-card border border-border text-[13px] text-foreground shadow-lg flex items-center gap-2"
          ><AlertCircle size={14} className="text-accent" />{toast}</motion.div>
        )}
      </AnimatePresence>

      <AnimateIn>
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-foreground/25" />
            <input type="text" placeholder="搜索 RSS 内容..." value={keyword} onChange={(e) => setKeyword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setPage(1)}
              className="w-full pl-11 pr-4 py-2.5 bg-muted border border-border rounded-xl text-[14px] text-foreground placeholder:text-foreground/25 focus:outline-none focus:border-accent/30 transition-colors"
            />
          </div>
          <Dropdown value={selectedFeed} onChange={(val) => { setSelectedFeed(val); setPage(1) }} placeholder="全部订阅源" minWidth={130}
            options={[{ value: "", label: "全部订阅源" }, ...feeds.map((f) => ({ value: f.id, label: f.name }))]}
          />
          <button onClick={() => setShowDiscover(true)}
            className={cn("p-2.5 rounded-xl border transition-all",
              "bg-muted border-border text-muted-foreground hover:text-foreground"
            )}
          ><Compass size={16} /></button>
          <button onClick={() => setShowManager(!showManager)}
            className={cn("p-2.5 rounded-xl border transition-all",
              showManager ? "bg-muted border-border" : "bg-muted border-border text-muted-foreground hover:text-foreground"
            )}
          ><Settings2 size={16} /></button>
          <button onClick={async () => {
            await apiFetch("/rss/fetch", { method: "POST" })
            fetchRss()
          }}
            className={cn("p-2.5 rounded-xl border transition-all",
              "bg-muted border-border text-muted-foreground hover:text-foreground"
            )}
          ><RefreshCw size={16} /></button>
        </div>
      </AnimateIn>

      {/* 发现订阅源弹窗 */}
      <AnimatePresence>
        {showDiscover && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-foreground/60 backdrop-blur-xl flex items-center justify-center p-6"
            onClick={() => { setShowDiscover(false); setDiscoverResults([]) }}
          >
            <motion.div initial={{ scale: 0.95, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.95, y: 20 }}
              className="w-full max-w-lg bg-card border border-border rounded-2xl p-6 max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-[17px] font-semibold text-foreground">发现订阅源</h2>
                <button onClick={() => { setShowDiscover(false); setDiscoverResults([]) }} className="p-1 text-foreground/30 hover:text-foreground/60"><X size={18} /></button>
              </div>
              <div className="flex gap-2 mb-4">
                <input placeholder="输入网站地址，如 https://36kr.com" value={discoverUrl} onChange={(e) => setDiscoverUrl(e.target.value)}
                  className="flex-1 px-3 py-2 bg-muted border border-border rounded-lg text-[13px] text-foreground placeholder:text-foreground/25 focus:outline-none" />
                <button onClick={discoverFeed} disabled={discoverLoading}
                  className={cn("px-4 py-2 rounded-lg text-[13px] font-medium disabled:opacity-50", "bg-accent text-accent-foreground")}>发现</button>
              </div>
              {discoverResults.length > 0 && (
                <div className="space-y-2">
                  {discoverResults.map((r, i) => (
                    <div key={i} className="flex items-center gap-3 p-3 rounded-xl bg-muted/50 border border-border">
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-medium text-foreground/80">{r.name}</p>
                        <p className="text-[11px] text-foreground/25 truncate">{r.url}</p>
                      </div>
                      <button onClick={() => { setNewFeedName(r.name); setNewFeedUrl(r.url); setShowDiscover(false); setShowManager(true) }}
                        className="p-1.5 rounded-lg bg-accent/10 text-accent hover:bg-accent/20"><Plus size={14} /></button>
                    </div>
                  ))}
                </div>
              )}

              {/* 自定义 CSS 发现 */}
              <div className="border-t border-border mt-6 pt-4">
                <button onClick={() => setShowCustomDiscover(!showCustomDiscover)} className="flex items-center gap-2 text-[13px] text-foreground/50 hover:text-foreground/70">
                  <Code size={14} />{showCustomDiscover ? "收起自定义发现" : "自定义 CSS 发现"}
                </button>
                {showCustomDiscover && (
                  <div className="space-y-2 mt-3">
                    <input placeholder="网站 URL" value={customUrl} onChange={(e) => setCustomUrl(e.target.value)}
                      className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-[13px] text-foreground placeholder:text-foreground/25 focus:outline-none" />
                    <input placeholder="条目选择器，如 .article-item" value={customItemSelector} onChange={(e) => setCustomItemSelector(e.target.value)}
                      className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-[13px] text-foreground placeholder:text-foreground/25 focus:outline-none" />
                    <input placeholder="标题选择器（可选）" value={customTitleSelector} onChange={(e) => setCustomTitleSelector(e.target.value)}
                      className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-[13px] text-foreground placeholder:text-foreground/25 focus:outline-none" />
                    <button onClick={customDiscoverFeed} disabled={customLoading}
                      className={cn("w-full py-2 rounded-lg text-[13px] font-medium disabled:opacity-50", "bg-accent text-accent-foreground")}>
                      {customLoading ? "生成中..." : "生成 RSS 源"}
                    </button>
                    {customResult && <p className="text-[12px] text-accent break-all">{customResult}</p>}
                  </div>
                )}
              </div>

              {/* 微信公众号 RSS 发现 */}
              <div className="border-t border-border mt-6 pt-4">
                <button onClick={() => setShowWechatDiscover(!showWechatDiscover)} className="flex items-center gap-2 text-[13px] text-foreground/50 hover:text-foreground/70">
                  <span className="text-[12px]">💬</span>{showWechatDiscover ? "收起微信公众号" : "微信公众号 RSS"}
                </button>
                {showWechatDiscover && (
                  <div className="space-y-2 mt-3">
                    <p className="text-[11px] text-foreground/40">输入公众号主页链接（含 __biz 参数）或公众号名称</p>
                    <div className="flex gap-2">
                      <input placeholder="公众号链接或名称" value={wechatUrl} onChange={(e) => setWechatUrl(e.target.value)}
                        className="flex-1 px-3 py-2 bg-muted border border-border rounded-lg text-[13px] text-foreground placeholder:text-foreground/25 focus:outline-none" />
                      <button onClick={discoverWechat} disabled={wechatLoading}
                        className={cn("px-4 py-2 rounded-lg text-[13px] font-medium disabled:opacity-50", "bg-accent text-accent-foreground")}>
                        {wechatLoading ? "..." : "转换"}
                      </button>
                    </div>
                    {wechatResult && (
                      <div className="flex items-center gap-3 p-3 rounded-xl bg-muted/50 border border-border">
                        <div className="flex-1 min-w-0">
                          <p className="text-[13px] font-medium">{wechatResult.name}</p>
                          <p className="text-[11px] text-foreground/40 truncate">{wechatResult.feed_url}</p>
                          {wechatResult.warning && <p className="text-[11px] text-yellow-500 mt-0.5">{wechatResult.warning}</p>}
                        </div>
                        <button
                          onClick={() => { setNewFeedName(wechatResult.name); setNewFeedUrl(wechatResult.feed_url); setShowDiscover(false); setShowManager(true) }}
                          className="p-1.5 rounded-lg bg-accent/10 text-accent hover:bg-accent/20"
                        ><Plus size={14} /></button>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* AI 话题搜索 */}
              <div className="border-t border-border mt-6 pt-4">
                <button onClick={() => setShowAiSearch(!showAiSearch)} className="flex items-center gap-2 text-[13px] text-foreground/50 hover:text-foreground/70">
                  <span className="text-[12px]">🤖</span>{showAiSearch ? "收起 AI 搜索" : "AI 话题搜索"}
                </button>
                {showAiSearch && (
                  <div className="space-y-2 mt-3">
                    <p className="text-[11px] text-foreground/40">输入话题关键词，自动搜寻相关 RSS 订阅源</p>
                    <div className="flex gap-2">
                      <input placeholder="如：AI人工智能、A股股市" value={aiSearchTopic} onChange={(e) => setAiSearchTopic(e.target.value)}
                        className="flex-1 px-3 py-2 bg-muted border border-border rounded-lg text-[13px] text-foreground placeholder:text-foreground/25 focus:outline-none" />
                      <button onClick={searchAiRss} disabled={aiSearchLoading}
                        className={cn("px-4 py-2 rounded-lg text-[13px] font-medium disabled:opacity-50", "bg-accent text-accent-foreground")}>
                        {aiSearchLoading ? "搜索中..." : "搜索"}
                      </button>
                    </div>
                    {aiSearchResults.length > 0 && (
                      <div className="space-y-2">
                        {aiSearchResults.map((r, i) => (
                          <div key={i} className={cn(
                            "flex items-center gap-3 p-3 rounded-xl border",
                            r.verified ? "bg-muted/50 border-border" : "bg-muted/30 border-border/50 opacity-70"
                          )}>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <p className="text-[13px] font-medium text-foreground/80 truncate">{r.name}</p>
                                {r.verified && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-500/10 text-green-600 shrink-0">✓</span>}
                                {r.subscribers > 0 && <span className="text-[10px] text-foreground/30 shrink-0">{r.subscribers.toLocaleString()} 订阅</span>}
                              </div>
                              <p className="text-[11px] text-foreground/25 truncate">{r.feed_url}</p>
                            </div>
                            <button onClick={() => { setNewFeedName(r.name); setNewFeedUrl(r.feed_url); setShowDiscover(false); setShowManager(true) }}
                              className="p-1.5 rounded-lg bg-accent/10 text-accent hover:bg-accent/20 shrink-0"><Plus size={14} /></button>
                          </div>
                        ))}
                        <button
                          onClick={bulkSubscribeAi}
                          className={cn("w-full py-2 rounded-lg text-[13px] font-medium", "bg-accent/20 text-accent hover:bg-accent/30 transition-all")}
                        >
                          一键订阅全部 ({aiSearchResults.filter(r => r.verified).length} 个有效源)
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 管理订阅源弹窗 */}
      <AnimatePresence>
        {showManager && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-foreground/60 backdrop-blur-xl flex items-center justify-center p-6"
            onClick={() => { setShowManager(false); setEditingFeed(null) }}
          >
            <motion.div initial={{ scale: 0.95, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.95, y: 20 }}
              className="w-full max-w-lg bg-card border border-border rounded-2xl p-6 max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-[17px] font-semibold text-foreground">管理订阅源</h2>
                <button onClick={() => { setShowManager(false); setEditingFeed(null) }} className="p-1 text-foreground/30 hover:text-foreground/60"><X size={18} /></button>
              </div>
              <div className="flex gap-2 mb-6">
                <input placeholder="名称" value={newFeedName} onChange={(e) => setNewFeedName(e.target.value)}
                  className="flex-1 px-3 py-2 bg-muted border border-border rounded-lg text-[13px] text-foreground placeholder:text-foreground/25 focus:outline-none" />
                <input placeholder="URL" value={newFeedUrl} onChange={(e) => setNewFeedUrl(e.target.value)}
                  className="flex-[2] px-3 py-2 bg-muted border border-border rounded-lg text-[13px] text-foreground placeholder:text-foreground/25 focus:outline-none" />
                <button onClick={addFeed}
                  className={cn("p-2 rounded-lg", "bg-accent text-accent-foreground")}
                ><Plus size={16} /></button>
              </div>
              <div className="space-y-2">
                {feeds.map((feed) => (
                  <div key={feed.id} className="flex items-center gap-3 p-3 rounded-xl bg-muted/50 border border-border">
                    {editingFeed?.id === feed.id ? (
                      <>
                        <input value={editName} onChange={(e) => setEditName(e.target.value)}
                          className="flex-1 px-2 py-1 bg-background border border-border rounded text-[12px] text-foreground focus:outline-none" />
                        <input value={editUrl} onChange={(e) => setEditUrl(e.target.value)}
                          className="flex-[2] px-2 py-1 bg-background border border-border rounded text-[12px] text-foreground focus:outline-none" />
                        <button onClick={saveEditFeed} className="p-1 text-accent hover:text-accent/70"><Check size={14} /></button>
                        <button onClick={() => setEditingFeed(null)} className="p-1 text-foreground/30 hover:text-foreground/60"><X size={14} /></button>
                      </>
                    ) : (
                      <>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-[13px] font-medium text-foreground truncate">{feed.name}</p>
                            {feed.last_error ? (
                              <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-destructive/10 text-destructive">异常</span>
                            ) : feed.last_crawl_time ? (
                              <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-[#30d158]/10 text-[#30d158]">正常</span>
                            ) : (
                              <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-muted text-muted-foreground">待抓取</span>
                            )}
                          </div>
                          <p className="text-[11px] text-muted-foreground/60 truncate mt-0.5">{feed.url}</p>
                          {feed.last_error && <p className="text-[10px] text-destructive/70 mt-0.5 truncate">{feed.last_error}</p>}
                          {feed.last_crawl_time && !feed.last_error && <p className="text-[10px] text-muted-foreground/40 mt-0.5">最后抓取: {new Date(feed.last_crawl_time).toLocaleString("zh-CN", { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" })}</p>}
                        </div>
                        <button onClick={() => { setEditingFeed(feed); setEditName(feed.name); setEditUrl(feed.url) }}
                          className="p-1 text-muted-foreground/50 hover:text-foreground"><Edit3 size={13} /></button>
                        <button onClick={() => toggleFeed(feed)}
                          className={cn("w-8 h-5 rounded-full transition-all relative", feed.enabled ? "bg-accent" : "bg-muted")}
                        >
                          <span className={cn("absolute top-0.5 w-4 h-4 rounded-full bg-background transition-all", feed.enabled ? "left-[18px]" : "left-0.5")} />
                        </button>
                        <button onClick={() => deleteFeed(feed.id)} className="p-1 text-muted-foreground/40 hover:text-destructive"><X size={14} /></button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {loading ? <Loading /> : items.length === 0 ? (
        <Empty icon={<Rss size={40} />} title="暂无 RSS 内容" />
      ) : (
        <motion.div layout className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {items.map((item, i) => (
            <motion.article key={item.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03, duration: 0.3 }}
              className="group rounded-2xl bg-card border border-border p-5 hover:border-foreground/10 transition-all"
            >
              <div className="flex items-center gap-2 mb-3">
                <span className="px-2 py-0.5 rounded-md bg-accent/10 text-[11px] text-accent font-medium">{item.feed_name}</span>
                <span className="ml-auto text-[11px] text-muted-foreground/60 tabular-nums">{new Date(item.published_at).toLocaleDateString("zh-CN")}</span>
              </div>
              <h3 className="text-[15px] font-semibold tracking-tight text-foreground mb-2 line-clamp-2 group-hover:text-foreground transition-colors">{item.title}</h3>
              {item.summary && <p className="text-[13px] leading-relaxed text-muted-foreground line-clamp-2">{item.summary}</p>}
              {item.url && (
                <a href={item.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 mt-3 text-[12px] text-accent hover:text-accent/80 transition-colors">
                  查看原文 <ExternalLink size={11} />
                </a>
              )}
            </motion.article>
          ))}
        </motion.div>
      )}
    </div>
  )
}

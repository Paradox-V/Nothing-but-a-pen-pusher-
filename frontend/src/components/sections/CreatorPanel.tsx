import { useState, useEffect, useRef, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { PenTool, Sparkles, RefreshCw, Image, Send, AlertCircle, Loader2, FileText, ChevronRight } from "lucide-react"
import { marked } from "marked"
import DOMPurify from "dompurify"
import { cn } from "@/lib/utils"
import { Loading } from "@/components/shared/Loading"
import { Empty } from "@/components/shared/Empty"

import { Dropdown } from "@/components/shared/Dropdown"
import { useTheme } from "@/hooks/use-theme"
import { apiFetch } from "@/hooks/use-api"

interface Hotspot {
  id?: number
  title: string
  summary: string
  source: string
  url: string
  date: string
  similarity: number
}
interface TopicResult { hotspot: Hotspot; titles: string[]; explanation: string }
interface Framework { id: string; framework_text: string }

type View = "topics" | "framework" | "article"

const viewTransition = { initial: { opacity: 0, x: 20 }, animate: { opacity: 1, x: 0 }, exit: { opacity: 0, x: -20 }, transition: { duration: 0.2 } }

export function CreatorPanel() {
  const [view, setView] = useState<View>("topics")

  // 选题页
  const [industries, setIndustries] = useState<string[]>([])
  const [industry, setIndustry] = useState("")
  const [topicKeyword, setTopicKeyword] = useState("")
  const [topics, setTopics] = useState<TopicResult[]>([])
  const [loadingTopics, setLoadingTopics] = useState(false)
  const [regeneratingIdx, setRegeneratingIdx] = useState<number | null>(null)
  const [creatingTitle, setCreatingTitle] = useState<string | null>(null)

  // 框架页
  const [selectedTitle, setSelectedTitle] = useState("")
  const [framework, setFramework] = useState<Framework | null>(null)
  const [chatInput, setChatInput] = useState("")
  const [sendingChat, setSendingChat] = useState(false)

  // 成文页
  const [imageCount, setImageCount] = useState(2)
  const [generating, setGenerating] = useState(false)
  const [genProgress, setGenProgress] = useState("")
  const [article, setArticle] = useState("")
  const [editMode, setEditMode] = useState(false)
  const [editContent, setEditContent] = useState("")

  const [toast, setToast] = useState<string | null>(null)
  const { theme } = useTheme()
  const v = theme === "vintage"
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const toastRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = (msg: string) => {
    if (toastRef.current) clearTimeout(toastRef.current)
    setToast(msg)
    toastRef.current = setTimeout(() => setToast(null), 4000)
  }

  useEffect(() => {
    apiFetch("/topic/industries").then((r) => r.json()).then(setIndustries).catch(() => showToast("行业列表加载失败"))
  }, [])

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      if (toastRef.current) clearTimeout(toastRef.current)
    }
  }, [])

  // ── 选题 ──

  const generateTopics = async () => {
    if (!industry || !topicKeyword.trim()) return
    setLoadingTopics(true)
    setTopics([])
    try {
      const res = await apiFetch("/topic/generate", { method: "POST", body: JSON.stringify({ industry, keyword: topicKeyword, top_k: 5 }) })
      const data = await res.json()
      if (!res.ok) { showToast(data.error || "选题生成失败"); return }
      setTopics(Array.isArray(data) ? data : [])
    } catch { showToast("选题生成失败，请检查网络") } finally { setLoadingTopics(false) }
  }

  const regenerateTitles = async (idx: number) => {
    const topic = topics[idx]
    if (!topic) return
    setRegeneratingIdx(idx)
    try {
      const res = await apiFetch("/topic/regenerate-titles", {
        method: "POST",
        body: JSON.stringify({ hotspot: { title: topic.hotspot.title, summary: topic.hotspot.summary }, industry, keyword: topicKeyword }),
      })
      const data = await res.json()
      if (!res.ok) { showToast(data.error || "重新生成失败"); return }
      const updated = [...topics]
      updated[idx] = { ...topic, titles: data.titles || [] }
      setTopics(updated)
    } catch { showToast("重新生成失败") } finally { setRegeneratingIdx(null) }
  }

  const startCreation = async (title: string, topic: TopicResult) => {
    setCreatingTitle(title)
    try {
      const res = await apiFetch("/creator/framework/create", {
        method: "POST",
        body: JSON.stringify({ title, topic_summary: topic.hotspot.summary, source: topic.hotspot.source, industry, keyword: topicKeyword }),
      })
      const data = await res.json()
      if (!res.ok) { showToast(data.error || "创建框架失败"); return }
      setSelectedTitle(title)
      // 合并 article_structure + writing_approach 为一个文本
      const combined = `【文章结构】\n${data.article_structure || ""}\n\n【写作思路】\n${data.writing_approach || ""}`
      setFramework({ id: data.id, framework_text: combined })
      setChatInput("")
      setView("framework")
    } catch { showToast("创建框架失败") } finally { setCreatingTitle(null) }
  }

  // ── 框架 ──

  const chatFramework = useCallback(async () => {
    if (!framework || !chatInput.trim() || sendingChat) return
    setSendingChat(true)
    try {
      const res = await apiFetch(`/creator/framework/${framework.id}/update`, {
        method: "POST",
        body: JSON.stringify({ message: chatInput }),
      })
      const data = await res.json()
      if (!res.ok) { showToast(data.error || "调整框架失败"); return }
      const combined = `【文章结构】\n${data.article_structure || ""}\n\n【写作思路】\n${data.writing_approach || ""}`
      setFramework({ ...framework, framework_text: combined })
      setChatInput("")
    } catch { showToast("调整框架失败，请重试") } finally { setSendingChat(false) }
  }, [framework, chatInput, sendingChat])

  const saveFramework = async () => {
    if (!framework) return
    const text = framework.framework_text
    // 拆分回两个字段保存
    const structMatch = text.match(/【文章结构】\n?([\s\S]*?)(?=\n【写作思路】|$)/)
    const approachMatch = text.match(/【写作思路】\n?([\s\S]*?)$/)
    const article_structure = (structMatch ? structMatch[1] : text).trim()
    const writing_approach = (approachMatch ? approachMatch[1] : "").trim()
    try {
      await apiFetch(`/creator/framework/${framework.id}/save`, {
        method: "POST",
        body: JSON.stringify({ article_structure, writing_approach }),
      })
    } catch { /* 静默 */ }
  }

  const confirmAndGoArticle = () => {
    saveFramework()
    setArticle("")
    setEditMode(false)
    setGenProgress("")
    setView("article")
  }

  // ── 成文 ──

  const generateArticle = async () => {
    if (!framework) return
    setGenerating(true)
    setGenProgress("正在确认框架...")
    try {
      const confirmRes = await apiFetch(`/creator/framework/${framework.id}/confirm`, { method: "POST" })
      if (!confirmRes.ok) { showToast("确认框架失败"); setGenerating(false); return }
      setGenProgress("正在启动生成...")
      const genRes = await apiFetch(`/creator/framework/${framework.id}/generate`, { method: "POST", body: JSON.stringify({ image_count: imageCount }) })
      const genData = await genRes.json()
      if (!genRes.ok || !genData.task_id) { showToast(genData.error || "启动生成失败"); setGenerating(false); return }
      const taskId = genData.task_id
      setGenProgress("AI 正在撰写文章...")
      if (pollRef.current) clearInterval(pollRef.current)
      let dots = 0
      pollRef.current = setInterval(async () => {
        dots = (dots + 1) % 4
        setGenProgress(`AI 正在撰写文章${".".repeat(dots + 1)}`)
        try {
          const s = await (await apiFetch(`/creator/task/${taskId}/status`)).json()
          if (s.status === "completed") {
            clearInterval(pollRef.current!); pollRef.current = null
            setGenProgress("文章生成完成！")
            const r = await (await apiFetch(`/creator/task/${taskId}/result`)).json()
            setArticle(r.article || r.content || "")
            setGenerating(false)
          } else if (s.status === "failed") {
            clearInterval(pollRef.current!); pollRef.current = null
            showToast("文章生成失败"); setGenerating(false)
          }
        } catch {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
          showToast("任务状态查询失败"); setGenerating(false)
        }
      }, 2000)
    } catch { showToast("文章生成失败"); setGenerating(false) }
  }

  const renderMarkdown = (text: string) => DOMPurify.sanitize(marked.parse(text, { breaks: true }) as string)

  // ── 步骤指示器 ──
  const steps = [
    { key: "topics", label: "选题" },
    { key: "framework", label: "框架" },
    { key: "article", label: "成文" },
  ] as const
  const currentIdx = steps.findIndex((s) => s.key === view)

  // ── 渲染 ──

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-[100] px-4 py-2.5 rounded-xl bg-card border border-border text-[13px] text-foreground shadow-lg flex items-center gap-2">
          <AlertCircle size={14} className="text-accent" />{toast}
        </div>
      )}

      {/* 步骤条 */}
      {view !== "topics" && (
        <div className="flex items-center gap-2 mb-6">
          {steps.map((step, i) => (
            <div key={step.key} className="flex items-center gap-2">
              <button
                onClick={() => {
                  if (i === 0) { setView("topics"); setFramework(null); setArticle(""); }
                  else if (i === 1 && framework) setView("framework")
                  else if (i === 2 && framework) setView("article")
                }}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1 rounded-full text-[12px] font-medium transition-all",
                  i <= currentIdx
                    ? "bg-accent/15 text-accent"
                    : "bg-muted text-muted-foreground",
                  i < currentIdx && "cursor-pointer hover:bg-accent/25"
                )}
              >
                <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold bg-accent/20">{i + 1}</span>
                {step.label}
              </button>
              {i < steps.length - 1 && <ChevronRight size={12} className="text-muted-foreground/40" />}
            </div>
          ))}
        </div>
      )}

      <AnimatePresence mode="wait">
        {/* ══════ 选题页 ══════ */}
        {view === "topics" && (
          <motion.div key="topics" {...viewTransition}>
            <div className="mb-8">
              <h2 className="text-[20px] font-semibold tracking-tight mb-4 text-foreground">选题生成</h2>
              <div className="flex items-center gap-3">
                <Dropdown value={industry} onChange={setIndustry} placeholder="选择行业" minWidth={140}
                  options={[{ value: "", label: "选择行业", disabled: true }, ...industries.map((ind) => ({ value: ind, label: ind }))]}
                />
                <input placeholder="关键词（必填）" value={topicKeyword} onChange={(e) => setTopicKeyword(e.target.value)}
                  className={cn("flex-1 px-4 py-2.5 bg-muted border border-border rounded-xl text-[14px] text-foreground focus:outline-none focus:border-accent/30", v ? "placeholder:text-foreground/45" : "placeholder:text-muted-foreground")}
                />
                <button onClick={generateTopics} disabled={loadingTopics || !industry || !topicKeyword.trim()}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-[13px] font-semibold transition-all disabled:opacity-50 bg-accent text-accent-foreground hover:bg-accent/80"
                ><Sparkles size={14} />{loadingTopics ? "生成中..." : "生成选题"}</button>
              </div>
            </div>

            {loadingTopics ? (
              <Loading text="AI 正在搜索新闻并生成选题" />
            ) : topics.length > 0 ? (
              <div className="space-y-4">
                {topics.map((topic, i) => (
                  <motion.div key={i} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                    className="rounded-2xl bg-card border border-border p-5"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <span className="px-2 py-0.5 rounded-md bg-muted text-[11px] text-muted-foreground">{topic.hotspot.source}</span>
                      <span className="text-[11px] text-muted-foreground/60">{topic.hotspot.date}</span>
                      <span className="px-2 py-0.5 rounded-md bg-accent/10 text-[11px] text-accent tabular-nums">{Math.round(topic.hotspot.similarity * 100)}%</span>
                    </div>
                    <h3 className="text-[15px] font-semibold text-foreground mb-1">{topic.hotspot.title}</h3>
                    <p className="text-[13px] text-muted-foreground leading-relaxed mb-4">{topic.hotspot.summary}</p>

                    <div className="space-y-2 border-t border-border/50 pt-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[11px] text-muted-foreground uppercase tracking-wider">AI 选题建议</span>
                        <button onClick={() => regenerateTitles(i)} disabled={regeneratingIdx === i}
                          className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-muted text-[11px] text-muted-foreground hover:text-foreground transition-all disabled:opacity-50"
                        >
                          <RefreshCw size={10} className={cn(regeneratingIdx === i && "animate-spin")} />
                          重新生成
                        </button>
                      </div>
                      {regeneratingIdx === i ? (
                        <div className="flex items-center gap-2 py-2 text-[12px] text-muted-foreground">
                          <Loader2 size={12} className="animate-spin" />正在重新生成选题...
                        </div>
                      ) : (
                        topic.titles?.map((title, tIdx) => (
                          <div key={tIdx} className="flex items-center gap-3 py-1.5 px-3 rounded-xl hover:bg-muted/50 transition-all group">
                            <span className="flex-1 text-[13px] text-foreground/90 leading-snug">{title}</span>
                            <button onClick={() => startCreation(title, topic)} disabled={creatingTitle !== null}
                              className="shrink-0 flex items-center gap-1 px-3 py-1 rounded-lg bg-accent text-accent-foreground text-[11px] font-medium hover:bg-accent/80 transition-all disabled:opacity-50"
                            >
                              {creatingTitle === title ? <Loader2 size={11} className="animate-spin" /> : <PenTool size={11} />}
                              开始创作
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  </motion.div>
                ))}
              </div>
            ) : !industry ? (
              <Empty icon={<PenTool size={40} />} title="选择行业开始创作" description="AI 将基于热点生成选题建议" />
            ) : null}
          </motion.div>
        )}

        {/* ══════ 框架页 ══════ */}
        {view === "framework" && (
          <motion.div key="framework" {...viewTransition}>
            <div className="flex items-center gap-3 mb-6">
              <h2 className="text-[16px] font-semibold text-foreground">{selectedTitle}</h2>
            </div>

            {framework && (
              <div className="rounded-2xl bg-card border border-border p-5 mb-6">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-[14px] font-semibold text-foreground">文章框架</span>
                  <span className="text-[11px] text-muted-foreground">可直接编辑文本内容</span>
                </div>
                <textarea
                  value={framework.framework_text}
                  onChange={(e) => setFramework({ ...framework, framework_text: e.target.value })}
                  onBlur={saveFramework}
                  rows={12}
                  className="w-full p-3 bg-muted border border-border rounded-xl text-[13px] text-foreground leading-relaxed focus:outline-none focus:border-accent/30 resize-y"
                />

                {/* 修改意见 */}
                <div className="flex items-center gap-2 mt-4">
                  <input
                    placeholder="输入修改意见，如：增加案例分析、调整语气..."
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); chatFramework() } }}
                    disabled={sendingChat}
                    className={cn("flex-1 px-3 py-2.5 bg-muted border border-border rounded-xl text-[13px] text-foreground focus:outline-none focus:border-accent/30 disabled:opacity-50", v ? "placeholder:text-foreground/45" : "placeholder:text-muted-foreground")}
                  />
                  <button onClick={chatFramework} disabled={sendingChat || !chatInput.trim()}
                    className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-accent text-accent-foreground text-[13px] font-medium hover:bg-accent/80 transition-all disabled:opacity-50"
                  >
                    {sendingChat ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                    {sendingChat ? "调整中..." : "发送"}
                  </button>
                </div>
              </div>
            )}

            <div className="flex justify-end">
              <button onClick={confirmAndGoArticle}
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-[13px] font-semibold transition-all bg-primary text-primary-foreground hover:bg-primary/90"
              >
                <FileText size={14} />
                确认框架，进入成文
                <ChevronRight size={14} />
              </button>
            </div>
          </motion.div>
        )}

        {/* ══════ 成文页 ══════ */}
        {view === "article" && (
          <motion.div key="article" {...viewTransition}>
            <div className="flex items-center gap-3 mb-6">
              <h2 className="text-[16px] font-semibold text-foreground">{selectedTitle}</h2>
            </div>

            {/* 配图设置 + 生成按钮 */}
            <div className="rounded-2xl bg-card border border-border p-5 mb-6">
              <div className="flex items-center justify-between flex-wrap gap-4">
                <div className="flex items-center gap-3">
                  <Image size={16} className="text-muted-foreground" />
                  <span className="text-[13px] text-foreground">配图数量</span>
                  <div className="relative z-[60]">
                    <Dropdown value={String(imageCount)} onChange={(val) => setImageCount(Number(val))}
                      options={[0, 1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `${n} 张` }))}
                      minWidth={80}
                    />
                  </div>
                </div>
                <button onClick={generateArticle} disabled={generating}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-[13px] font-semibold transition-all disabled:opacity-50 bg-accent text-accent-foreground hover:bg-accent/80"
                >
                  {generating ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  {generating ? "生成中..." : article ? "重新生成" : "开始生成文章"}
                </button>
              </div>
            </div>

            {/* 生成进度 */}
            {generating && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="rounded-2xl bg-card border border-accent/20 p-6 mb-6 text-center">
                <Loader2 size={28} className="animate-spin text-accent mx-auto mb-3" />
                <p className="text-[14px] text-foreground font-medium">{genProgress}</p>
                <p className="text-[12px] text-muted-foreground mt-1">预计需要 1-2 分钟，请耐心等待</p>
              </motion.div>
            )}

            {/* 文章结果 */}
            {article && !generating && (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="rounded-2xl bg-card border border-border p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-[15px] font-semibold text-foreground">文章结果</h3>
                  <div className="flex items-center gap-2">
                    {editMode && (
                      <button onClick={() => { setArticle(editContent); setEditMode(false) }}
                        className="px-3 py-1 rounded-lg bg-accent/10 text-[12px] text-accent hover:bg-accent/20"
                      >保存修改</button>
                    )}
                    <button onClick={() => { if (!editMode) setEditContent(article); setEditMode(!editMode) }}
                      className="px-3 py-1 rounded-lg bg-muted text-[12px] text-muted-foreground hover:text-foreground"
                    >{editMode ? "预览" : "编辑"}</button>
                  </div>
                </div>
                {editMode ? (
                  <textarea value={editContent} onChange={(e) => setEditContent(e.target.value)} rows={20}
                    className="w-full p-3 bg-muted border border-border rounded-xl text-[13px] text-foreground focus:outline-none resize-y font-mono" />
                ) : (
                  <div className="prose prose-sm max-w-none text-foreground/80" dangerouslySetInnerHTML={{ __html: renderMarkdown(article) }} />
                )}
              </motion.div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

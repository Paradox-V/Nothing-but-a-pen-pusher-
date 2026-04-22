import { useState, useEffect, useRef } from "react"
import { motion } from "framer-motion"
import { PenTool, Sparkles, RefreshCw, Image, ChevronDown, ChevronUp, Send, AlertCircle } from "lucide-react"
import { marked } from "marked"
import * as DOMPurify from "dompurify"
import { cn } from "@/lib/utils"
import { Loading } from "@/components/shared/Loading"
import { Empty } from "@/components/shared/Empty"
import { AnimateIn } from "@/components/shared/AnimateIn"
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
interface Framework { id: string; article_structure: string; writing_approach: string }

export function CreatorPanel() {
  const [industries, setIndustries] = useState<string[]>([])
  const [industry, setIndustry] = useState("")
  const [topicKeyword, setTopicKeyword] = useState("")
  const [topics, setTopics] = useState<TopicResult[]>([])
  const [loadingTopics, setLoadingTopics] = useState(false)
  const [framework, setFramework] = useState<Framework | null>(null)
  const [frameworkOpen, setFrameworkOpen] = useState(true)
  const [chatInput, setChatInput] = useState("")
  const [imageCount, setImageCount] = useState(2)
  const [generating, setGenerating] = useState(false)
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

  const generateTopics = async () => {
    if (!industry || !topicKeyword.trim()) return
    setLoadingTopics(true)
    try {
      const res = await apiFetch("/topic/generate", { method: "POST", body: JSON.stringify({ industry, keyword: topicKeyword, top_k: 5 }) })
      const data = await res.json()
      if (!res.ok) { showToast(data.error || "选题生成失败"); return }
      setTopics(Array.isArray(data) ? data : [])
    } catch { showToast("选题生成失败，请检查网络"); setTopics([]) } finally { setLoadingTopics(false) }
  }

  const selectTitle = async (title: string, topic: TopicResult) => {
    try {
      const res = await apiFetch("/creator/framework/create", {
        method: "POST",
        body: JSON.stringify({
          title,
          topic_summary: topic.hotspot.summary,
          source: topic.hotspot.source,
          industry,
          keyword: topicKeyword,
        }),
      })
      const data = await res.json()
      if (!res.ok) { showToast(data.error || "创建框架失败"); return }
      setFramework({ id: data.id, article_structure: data.article_structure, writing_approach: data.writing_approach })
      setArticle(""); setFrameworkOpen(true)
    } catch { showToast("创建框架失败") }
  }

  const chatFramework = async () => {
    if (!framework || !chatInput.trim()) return
    try {
      const res = await apiFetch(`/creator/framework/${framework.id}/update`, { method: "POST", body: JSON.stringify({ message: chatInput }) })
      const data = await res.json()
      if (!res.ok) { showToast(data.error || "调整框架失败"); return }
      setFramework({ ...framework, article_structure: data.article_structure, writing_approach: data.writing_approach }); setChatInput("")
    } catch { showToast("调整框架失败") }
  }

  const saveFramework = async () => {
    if (!framework) return
    try {
      await apiFetch(`/creator/framework/${framework.id}/save`, {
        method: "POST",
        body: JSON.stringify({ article_structure: framework.article_structure, writing_approach: framework.writing_approach }),
      })
    } catch { /* 静默保存失败不阻塞 */ }
  }

  const generateArticle = async () => {
    if (!framework) return
    setGenerating(true)
    try {
      const confirmRes = await apiFetch(`/creator/framework/${framework.id}/confirm`, { method: "POST" })
      if (!confirmRes.ok) { showToast("确认框架失败"); setGenerating(false); return }
      const genRes = await apiFetch(`/creator/framework/${framework.id}/generate`, { method: "POST", body: JSON.stringify({ image_count: imageCount }) })
      const genData = await genRes.json()
      if (!genRes.ok || !genData.task_id) { showToast(genData.error || "启动生成失败"); setGenerating(false); return }
      const taskId = genData.task_id
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(async () => {
        try {
          const s = await (await apiFetch(`/creator/task/${taskId}/status`)).json()
          if (s.status === "completed") { clearInterval(pollRef.current!); pollRef.current = null; const r = await (await apiFetch(`/creator/task/${taskId}/result`)).json(); setArticle(r.article || r.content || ""); setGenerating(false) }
          else if (s.status === "failed") { clearInterval(pollRef.current!); pollRef.current = null; showToast("文章生成失败"); setGenerating(false) }
        } catch { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }; showToast("任务状态查询失败"); setGenerating(false) }
      }, 2000)
    } catch { showToast("文章生成失败"); setGenerating(false) }
  }

  const renderMarkdown = (text: string) => DOMPurify.sanitize(marked.parse(text, { breaks: true }) as string)

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-[100] px-4 py-2.5 rounded-xl bg-card border border-border text-[13px] text-foreground shadow-lg flex items-center gap-2">
          <AlertCircle size={14} className="text-accent" />{toast}
        </div>
      )}

      <AnimateIn>
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
              className={cn("flex items-center gap-2 px-5 py-2.5 rounded-xl text-[13px] font-semibold transition-all disabled:opacity-50",
                "bg-accent text-accent-foreground hover:bg-accent/80"
              )}
            ><Sparkles size={14} />{loadingTopics ? "生成中..." : "生成选题"}</button>
          </div>
        </div>
      </AnimateIn>

      {loadingTopics ? <Loading text="AI 生成选题中" /> : topics.length > 0 ? (
        <div className="space-y-3 mb-8">
          {topics.map((topic, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
              className="rounded-2xl bg-card border border-border p-5"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="px-2 py-0.5 rounded-md bg-muted text-[11px] text-muted-foreground">{topic.hotspot.source}</span>
                <span className="text-[11px] text-muted-foreground/60">{topic.hotspot.date}</span>
                <span className="px-2 py-0.5 rounded-md bg-accent/10 text-[11px] text-accent tabular-nums">{Math.round(topic.hotspot.similarity * 100)}%</span>
              </div>
              <h3 className="text-[15px] font-semibold text-foreground mb-2">{topic.hotspot.title}</h3>
              <p className="text-[13px] text-muted-foreground leading-relaxed mb-3">{topic.hotspot.summary}</p>
              {topic.explanation && <p className="text-[12px] text-muted-foreground/60 italic mb-3">{topic.explanation}</p>}
              {topic.titles?.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {topic.titles.map((title) => (
                    <button key={title} onClick={() => selectTitle(title, topic)}
                      className="px-3 py-1.5 rounded-lg bg-accent/10 border border-accent/20 text-[12px] text-accent hover:bg-accent/20 transition-all"
                    >{title}</button>
                  ))}
                </div>
              )}
            </motion.div>
          ))}
        </div>
      ) : !industry ? <Empty icon={<PenTool size={40} />} title="选择行业开始创作" description="AI 将基于热点生成选题建议" /> : null}

      {framework && (
        <AnimateIn className="mb-8">
          <div className="rounded-2xl bg-card border border-border overflow-hidden">
            <button onClick={() => setFrameworkOpen(!frameworkOpen)} className="w-full flex items-center justify-between p-5 text-left">
              <span className="text-[15px] font-semibold text-foreground">文章框架</span>
              {frameworkOpen ? <ChevronUp size={16} className="text-muted-foreground" /> : <ChevronDown size={16} className="text-muted-foreground" />}
            </button>
            {frameworkOpen && (
              <div className="px-5 pb-5 space-y-4">
                <div>
                  <label className="text-[11px] text-muted-foreground uppercase tracking-wider">文章结构</label>
                  <textarea value={framework.article_structure} onChange={(e) => setFramework({ ...framework, article_structure: e.target.value })} onBlur={saveFramework} rows={6}
                    className="w-full mt-1 p-3 bg-muted border border-border rounded-xl text-[13px] text-foreground focus:outline-none resize-y" />
                </div>
                <div>
                  <label className="text-[11px] text-muted-foreground uppercase tracking-wider">写作思路</label>
                  <textarea value={framework.writing_approach} onChange={(e) => setFramework({ ...framework, writing_approach: e.target.value })} onBlur={saveFramework} rows={4}
                    className="w-full mt-1 p-3 bg-muted border border-border rounded-xl text-[13px] text-foreground focus:outline-none resize-y" />
                </div>
                <div className="flex items-center gap-2">
                  <input placeholder="用自然语言调整框架..." value={chatInput} onChange={(e) => setChatInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && chatFramework()}
                    className={cn("flex-1 px-3 py-2 bg-muted border border-border rounded-lg text-[13px] text-foreground focus:outline-none", v ? "placeholder:text-foreground/45" : "placeholder:text-muted-foreground")} />
                  <button onClick={chatFramework} className="p-2 bg-muted rounded-lg text-muted-foreground hover:text-foreground"><Send size={14} /></button>
                </div>
                <div className="flex items-center gap-4 pt-2">
                  <div className="flex items-center gap-2">
                    <Image size={14} className="text-muted-foreground" /><span className="text-[12px] text-muted-foreground">配图</span>
                    <Dropdown value={String(imageCount)} onChange={(v) => setImageCount(Number(v))}
                      options={[0,1,2,3,4,5].map((n) => ({ value: String(n), label: `${n} 张` }))}
                      minWidth={72} className="text-[12px]" />
                  </div>
                  <button onClick={generateArticle} disabled={generating}
                    className={cn("ml-auto flex items-center gap-2 px-5 py-2 rounded-xl text-[13px] font-semibold transition-all disabled:opacity-50",
                      v ? "bg-accent text-white hover:bg-accent/80" : "bg-primary text-primary-foreground hover:bg-primary/90"
                    )}
                  ><RefreshCw size={14} className={cn(generating && "animate-spin")} />{generating ? "生成中..." : "确认并生成文章"}</button>
                </div>
              </div>
            )}
          </div>
        </AnimateIn>
      )}

      {article && (
        <AnimateIn>
          <div className="rounded-2xl bg-card border border-border p-6">
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
          </div>
        </AnimateIn>
      )}
    </div>
  )
}

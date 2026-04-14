import { useState, useEffect, useRef, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { MessageCircle, Plus, Send, Trash2, ExternalLink, Bot, MessageSquare } from "lucide-react"
import { cn } from "@/lib/utils"
import { Empty } from "@/components/shared/Empty"
import { useTheme } from "@/hooks/use-theme"
import { apiFetch } from "@/hooks/use-api"
import { marked } from "marked"
import DOMPurify from "dompurify"
import ToolCallCard from "@/components/shared/ToolCallCard"

interface Session { id: string; title: string; msg_count: number; mode?: string }
interface Message { role: "user" | "assistant"; content: string; sources?: string }
interface ToolEvent { tool: string; args: Record<string, unknown>; summary?: string }

function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { breaks: true }) as string)
}

function escapeHtml(text: string): string {
  const div = document.createElement("div")
  div.textContent = text
  return div.innerHTML
}

function parseSources(sourcesJson?: string): { title: string; url: string; source: string }[] {
  if (!sourcesJson) return []
  try {
    return JSON.parse(sourcesJson)
  } catch {
    return []
  }
}

export function ChatPanel() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeSession, setActiveSession] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState("")
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([])
  const [agentMode, setAgentMode] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { theme } = useTheme()
  const v = theme === "vintage"

  useEffect(() => { apiFetch("/chat/sessions").then((r) => r.json()).then(setSessions).catch(() => {}) }, [])

  const loadMessages = useCallback(async (sessionId: string) => {
    setActiveSession(sessionId)
    try {
      const data = await (await apiFetch(`/chat/sessions/${sessionId}/messages`)).json()
      setMessages(Array.isArray(data) ? data : [])
    } catch { setMessages([]) }
  }, [])

  const createSession = async () => {
    try {
      const res = await apiFetch("/chat/sessions", {
        method: "POST",
        body: JSON.stringify({ mode: agentMode ? "agent" : "simple" }),
      })
      if (!res.ok) {
        if (res.status === 401 || res.status === 503) {
          const data = await res.json().catch(() => ({}))
          const token = prompt(data.error || "请先设置管理密钥")
          if (token) { localStorage.setItem("_admin_token", token); return createSession() }
        }
        return
      }
      const data = await res.json()
      const s = { id: data.id, title: data.title || "新对话", msg_count: 0, mode: data.mode }
      setSessions((prev) => [s, ...prev]); setActiveSession(s.id); setMessages([])
    } catch (e) { console.error("create session error:", e) }
  }

  const deleteSession = async (id: string) => {
    await apiFetch(`/chat/sessions/${id}`, { method: "DELETE" })
    setSessions((prev) => prev.filter((s) => s.id !== id))
    if (activeSession === id) { setActiveSession(null); setMessages([]) }
  }

  const sendMessage = async () => {
    if (!activeSession || !input.trim() || streaming) return
    const userMsg = input.trim(); setInput("")
    setMessages((prev) => [...prev, { role: "user", content: userMsg }])
    setStreaming(true); setStreamContent(""); setToolEvents([])

    let collectedSources: { title: string; url: string }[] = []

    try {
      const res = await apiFetch(`/chat/sessions/${activeSession}/chat`, {
        method: "POST",
        body: JSON.stringify({ message: userMsg }),
      })
      if (!res.ok) {
        if (res.status === 401 || res.status === 503) {
          const data = await res.json().catch(() => ({}))
          const token = prompt(data.error || "请先设置管理密钥")
          if (token) { localStorage.setItem("_admin_token", token); setStreaming(false); return sendMessage() }
        }
        setStreaming(false); return
      }
      const reader = res.body?.getReader()
      if (!reader) return
      const decoder = new TextDecoder(); let buffer = ""; let fullContent = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n"); buffer = lines.pop() || ""
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          const raw = line.slice(6)
          if (raw === "[DONE]") break
          try {
            const event = JSON.parse(raw)
            if (event.type === "content") {
              fullContent += event.text; setStreamContent(fullContent)
            } else if (event.type === "sources") {
              const parsed = JSON.parse(event.data)
              collectedSources = parsed
            } else if (event.type === "tool_call") {
              setToolEvents((prev) => [...prev, { tool: event.tool, args: event.args || {} }])
            } else if (event.type === "tool_result") {
              setToolEvents((prev) => {
                const updated = [...prev]
                // Find the last matching tool_call and attach summary
                for (let i = updated.length - 1; i >= 0; i--) {
                  if (updated[i].tool === event.tool && !updated[i].summary) {
                    updated[i] = { ...updated[i], summary: event.summary }
                    break
                  }
                }
                return updated
              })
            }
          } catch { /* */ }
        }
      }
      setMessages((prev) => [...prev, { role: "assistant", content: fullContent, sources: collectedSources.length > 0 ? JSON.stringify(collectedSources) : undefined }])
    } catch { /* */ }
    setStreaming(false); setStreamContent(""); setToolEvents([])
  }

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages, streamContent])

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 flex gap-4 h-[calc(100vh-8rem)]">
      {/* Sidebar */}
      <div className="w-64 shrink-0 flex flex-col gap-2">
        {/* Mode Toggle */}
        <div className={cn("flex rounded-xl border p-0.5", v ? "border-[#4F7942]/20" : "border-border")}>
          <button
            onClick={() => setAgentMode(false)}
            className={cn("flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[12px] font-medium transition-all",
              !agentMode
                ? v ? "bg-[#4F7942] text-white" : "bg-accent text-accent-foreground"
                : v ? "text-[#2C2E31]/50 hover:text-[#2C2E31]/70" : "text-foreground/40 hover:text-foreground/60"
            )}
          ><MessageSquare size={13} /> 简单问答</button>
          <button
            onClick={() => setAgentMode(true)}
            className={cn("flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[12px] font-medium transition-all",
              agentMode
                ? v ? "bg-[#4F7942] text-white" : "bg-accent text-accent-foreground"
                : v ? "text-[#2C2E31]/50 hover:text-[#2C2E31]/70" : "text-foreground/40 hover:text-foreground/60"
            )}
          ><Bot size={13} /> Agent 模式</button>
        </div>

        <button onClick={createSession}
          className={cn("flex items-center justify-center gap-2 p-3 rounded-xl border text-[13px] transition-all",
            v ? "bg-[#4F7942]/10 border-[#4F7942]/20 text-[#4F7942] hover:bg-[#4F7942]/20" : "bg-muted border-border text-foreground/50 hover:text-foreground/70 hover:bg-muted"
          )}
        ><Plus size={14} /> 新对话</button>
        <div className="flex-1 overflow-auto space-y-1">
          {sessions.map((session) => (
            <div key={session.id}
              className={cn("group flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer transition-all",
                activeSession === session.id
                  ? v ? "bg-[#3B5E32] text-white" : "bg-muted text-foreground"
                  : v ? "text-[#2C2E31]/40 hover:bg-[#3B5E32]/10 hover:text-[#2C2E31]/70" : "text-foreground/40 hover:bg-muted/50 hover:text-foreground/60"
              )}
              onClick={() => loadMessages(session.id)}
            >
              {session.mode === "agent" && (
                <span className={cn("shrink-0 px-1 py-0.5 rounded text-[9px] font-bold",
                  v ? "bg-[#4F7942]/20 text-[#4F7942]" : "bg-accent/10 text-accent"
                )}>Agent</span>
              )}
              <span className="flex-1 text-[13px] truncate">{session.title}</span>
              <button onClick={(e) => { e.stopPropagation(); deleteSession(session.id) }}
                className="opacity-0 group-hover:opacity-100 p-1 text-foreground/20 hover:text-destructive transition-all"
              ><Trash2 size={12} /></button>
            </div>
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col rounded-2xl bg-card border border-border overflow-hidden">
        {!activeSession ? (
          <Empty icon={<MessageCircle size={40} />} title="开始对话" description={agentMode ? "Agent 模式：AI 会自动选择工具检索信息" : "创建一个新对话或选择已有会话"} />
        ) : (
          <>
            <div className="flex-1 overflow-auto p-6 space-y-4">
              <AnimatePresence>
                {messages.map((msg, i) => (
                  <motion.div key={i} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}
                    className={cn("flex", msg.role === "user" ? "justify-end" : "justify-start")}
                  >
                    <div className={cn("max-w-[70%] px-4 py-3 rounded-2xl text-[14px] leading-relaxed",
                      msg.role === "user" ? "bg-accent text-accent-foreground rounded-br-md" : "bg-muted text-foreground/70 rounded-bl-md"
                    )}>
                      <div dangerouslySetInnerHTML={{ __html: msg.role === "assistant" ? renderMarkdown(msg.content) : escapeHtml(msg.content) }} />
                      {msg.sources && parseSources(msg.sources).length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-3">
                          {parseSources(msg.sources).map((s, j) => (
                            <a key={j} href={s.url} target="_blank" rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-background/50 text-[11px] text-foreground/40 hover:text-foreground/60 transition-colors"
                            >{s.title || s.source} <ExternalLink size={9} /></a>
                          ))}
                        </div>
                      )}
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>

              {/* Agent tool events */}
              {streaming && toolEvents.length > 0 && (
                <div className="space-y-1">
                  {toolEvents.map((evt, i) => (
                    <ToolCallCard key={i} tool={evt.tool} args={evt.args} summary={evt.summary} />
                  ))}
                </div>
              )}

              {streaming && streamContent && (
                <div className="flex justify-start">
                  <div className="max-w-[70%] px-4 py-3 rounded-2xl rounded-bl-md bg-muted text-foreground/70 text-[14px] leading-relaxed">
                    <div dangerouslySetInnerHTML={{ __html: renderMarkdown(streamContent) }} />
                    <span className="inline-block w-1.5 h-4 bg-foreground/40 animate-pulse ml-0.5" />
                  </div>
                </div>
              )}
              {streaming && !streamContent && toolEvents.length === 0 && (
                <div className="flex justify-start">
                  <div className="px-4 py-3 rounded-2xl rounded-bl-md bg-muted">
                    <div className="flex gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-foreground/30 animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-foreground/30 animate-bounce" style={{ animationDelay: "150ms" }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-foreground/30 animate-bounce" style={{ animationDelay: "300ms" }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="p-4 border-t border-border">
              <div className="flex items-center gap-2">
                <input placeholder={agentMode ? "Agent 模式：AI 会自动选择工具..." : "输入消息..."} value={input} onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
                  disabled={streaming}
                  className={cn(
                    "flex-1 px-4 py-3 bg-muted border border-border rounded-xl text-[14px] text-foreground focus:outline-none focus:border-accent/30 disabled:opacity-50 transition-colors",
                    v ? "placeholder:text-[#2C2E31]/45" : "placeholder:text-foreground/25"
                  )}
                />
                <button onClick={sendMessage} disabled={streaming || !input.trim()}
                  className={cn("p-3 rounded-xl transition-all disabled:opacity-30",
                    v ? "bg-[#4F7942] text-white hover:bg-[#3B5E32]" : "bg-accent text-accent-foreground hover:bg-accent/90"
                  )}
                ><Send size={16} /></button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

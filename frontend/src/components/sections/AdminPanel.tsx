import { useState, useEffect, useCallback } from "react"
import { motion } from "framer-motion"
import {
  LayoutDashboard, Users, ClipboardList, ScrollText,
  MessageCircle, Rss, AlertCircle, CheckCircle, RefreshCw,
  Bot, WifiOff, Wifi
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "@/hooks/use-theme"
import { apiFetch } from "@/hooks/use-api"
import { Loading } from "@/components/shared/Loading"

interface Overview {
  users?: { total: number }
  monitor?: { total_tasks: number; active_tasks: number; today_push_success: number; today_push_fail: number }
  rss?: { total_feeds: number; enabled_feeds: number }
  news?: { total: number }
  wcf?: { bindings: number; enabled_bindings: number }
  scheduler?: { alive: boolean }
  ai?: { available: boolean }
}

type AdminTab = "overview" | "users" | "tasks" | "logs" | "wcf" | "rss"

export function AdminPanel() {
  const [tab, setTab] = useState<AdminTab>("overview")
  const [overview, setOverview] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(true)
  const { theme } = useTheme()
  const v = theme === "vintage"

  const fetchOverview = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch("/admin/overview")
      if (res.ok) setOverview(await res.json())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchOverview() }, [fetchOverview])

  const tabs: { key: AdminTab; label: string; icon: React.ReactNode }[] = [
    { key: "overview", label: "概览", icon: <LayoutDashboard size={14} /> },
    { key: "users", label: "用户", icon: <Users size={14} /> },
    { key: "tasks", label: "任务", icon: <ClipboardList size={14} /> },
    { key: "logs", label: "日志", icon: <ScrollText size={14} /> },
    { key: "wcf", label: "微信", icon: <MessageCircle size={14} /> },
    { key: "rss", label: "RSS", icon: <Rss size={14} /> },
  ]

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">管理员面板</h1>
        <button
          onClick={fetchOverview}
          className="p-2 rounded-full text-foreground/40 hover:text-foreground/70 hover:bg-muted transition-all"
        >
          <RefreshCw size={15} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 overflow-x-auto pb-1">
        {tabs.map(({ key, label, icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] font-medium whitespace-nowrap transition-all",
              tab === key
                ? v ? "bg-accent text-white" : "bg-muted text-foreground"
                : "text-foreground/50 hover:text-foreground/80"
            )}
          >
            {icon}
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === "overview" && <OverviewTab overview={overview} loading={loading} v={v} />}
      {tab === "users" && <UsersTab v={v} />}
      {tab === "tasks" && <TasksTab v={v} />}
      {tab === "logs" && <LogsTab v={v} />}
      {tab === "wcf" && <WcfTab v={v} />}
      {tab === "rss" && <RssTab v={v} />}
    </div>
  )
}

// ── Overview Tab ────────────────────────────────────────────────

function OverviewTab({ overview, loading, v }: { overview: Overview | null; loading: boolean; v: boolean }) {
  if (loading) return <Loading />
  if (!overview) return <div className="text-foreground/40 text-[13px]">加载失败，请检查管理员 Token</div>

  const cards = [
    { label: "用户总数", value: overview.users?.total ?? 0, icon: <Users size={18} /> },
    { label: "监控任务", value: `${overview.monitor?.active_tasks ?? 0} / ${overview.monitor?.total_tasks ?? 0}`, icon: <ClipboardList size={18} />, sub: "活跃/总计" },
    { label: "RSS 订阅", value: `${overview.rss?.enabled_feeds ?? 0} / ${overview.rss?.total_feeds ?? 0}`, icon: <Rss size={18} />, sub: "启用/总计" },
    { label: "新闻总量", value: (overview.news?.total ?? 0).toLocaleString(), icon: <ScrollText size={18} /> },
    { label: "微信联系人", value: `${overview.wcf?.enabled_bindings ?? 0} / ${overview.wcf?.bindings ?? 0}`, icon: <MessageCircle size={18} />, sub: "启用/总计" },
    { label: "今日推送", value: `${overview.monitor?.today_push_success ?? 0}成功 / ${overview.monitor?.today_push_fail ?? 0}失败`, icon: <CheckCircle size={18} /> },
  ]

  return (
    <div className="space-y-6">
      {/* Status row */}
      <div className="flex gap-3 flex-wrap">
        <StatusBadge label="调度器" ok={overview.scheduler?.alive ?? false} v={v} />
        <StatusBadge label="AI 服务" ok={overview.ai?.available ?? false} v={v} />
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {cards.map((card) => (
          <motion.div
            key={card.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn(
              "rounded-2xl border p-4 space-y-2",
              v ? "border-accent/20 bg-accent/5" : "border-border bg-muted/30"
            )}
          >
            <div className={cn("text-foreground/50", v && "text-accent/60")}>{card.icon}</div>
            <div className="text-[13px] text-foreground/50">{card.label}</div>
            <div className="text-xl font-semibold">{card.value}</div>
            {card.sub && <div className="text-[11px] text-foreground/40">{card.sub}</div>}
          </motion.div>
        ))}
      </div>
    </div>
  )
}

function StatusBadge({ label, ok, v }: { label: string; ok: boolean; v: boolean }) {
  return (
    <div className={cn(
      "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] font-medium border",
      ok
        ? v ? "border-accent/30 bg-accent/10 text-accent" : "border-green-500/30 bg-green-500/10 text-green-600"
        : "border-red-500/30 bg-red-500/10 text-red-500"
    )}>
      {ok ? <Wifi size={12} /> : <WifiOff size={12} />}
      {label}：{ok ? "正常" : "异常"}
    </div>
  )
}

// ── Users Tab ───────────────────────────────────────────────────

function UsersTab({ v }: { v: boolean }) {
  const [users, setUsers] = useState<{ items: Record<string, unknown>[]; total: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)

  const fetchUsers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch(`/admin/users?page=${page}&page_size=20`)
      if (res.ok) setUsers(await res.json())
    } finally {
      setLoading(false)
    }
  }, [page])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  const toggleEnabled = async (userId: string, enabled: boolean) => {
    await apiFetch(`/admin/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: enabled ? 1 : 0 }),
    })
    fetchUsers()
  }

  const deleteUser = async (userId: string) => {
    if (!confirm("确定要删除该用户吗？")) return
    await apiFetch(`/admin/users/${userId}`, { method: "DELETE" })
    fetchUsers()
  }

  if (loading) return <Loading />

  return (
    <div className="space-y-4">
      <div className="text-[13px] text-foreground/50">共 {users?.total ?? 0} 位用户</div>
      <div className="space-y-2">
        {(users?.items ?? []).map((u: Record<string, unknown>) => (
          <div
            key={u.id as string}
            className={cn(
              "flex items-center justify-between p-3 rounded-xl border",
              v ? "border-accent/20 bg-accent/5" : "border-border bg-muted/20"
            )}
          >
            <div>
              <div className="text-[14px] font-medium">{u.username as string}</div>
              <div className="text-[12px] text-foreground/40">
                {u.email as string || "无邮箱"} · {u.role as string} · 注册 {(u.created_at as string)?.slice(0, 10)}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => toggleEnabled(u.id as string, !(u.enabled as number))}
                className={cn(
                  "text-[12px] px-2.5 py-1 rounded-lg border transition-all",
                  u.enabled
                    ? "border-red-400/30 text-red-400 hover:bg-red-400/10"
                    : "border-green-500/30 text-green-500 hover:bg-green-500/10"
                )}
              >
                {u.enabled ? "禁用" : "启用"}
              </button>
              <button
                onClick={() => deleteUser(u.id as string)}
                className="text-[12px] px-2.5 py-1 rounded-lg border border-red-500/30 text-red-500 hover:bg-red-500/10 transition-all"
              >
                删除
              </button>
            </div>
          </div>
        ))}
      </div>
      <PageControls page={page} total={users?.total ?? 0} pageSize={20} onPage={setPage} v={v} />
    </div>
  )
}

// ── Tasks Tab ────────────────────────────────────────────────────

function TasksTab({ v }: { v: boolean }) {
  const [tasks, setTasks] = useState<{ items: Record<string, unknown>[]; total: number } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiFetch("/admin/tasks?page_size=50")
      .then((r) => r.json())
      .then(setTasks)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Loading />

  return (
    <div className="space-y-4">
      <div className="text-[13px] text-foreground/50">共 {tasks?.total ?? 0} 个监控任务</div>
      <div className="space-y-2">
        {(tasks?.items ?? []).map((t: Record<string, unknown>) => {
          const keywords = Array.isArray(t.keywords) ? (t.keywords as string[]).join("、") : String(t.keywords ?? "")
          return (
            <div
              key={t.id as string}
              className={cn(
                "p-3 rounded-xl border",
                v ? "border-accent/20 bg-accent/5" : "border-border bg-muted/20"
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-[14px] font-medium">{t.name as string}</span>
                <span className={cn(
                  "text-[11px] px-2 py-0.5 rounded-full",
                  t.is_active
                    ? "bg-green-500/10 text-green-600"
                    : "bg-foreground/10 text-foreground/40"
                )}>
                  {t.is_active ? "活跃" : "停用"}
                </span>
              </div>
              <div className="text-[12px] text-foreground/40 mt-1">
                关键词：{keywords} · 调度：{t.schedule as string}
                {t.owner_id && ` · 归属：${(t.owner_id as string).slice(0, 8)}...`}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Logs Tab ─────────────────────────────────────────────────────

function LogsTab({ v }: { v: boolean }) {
  const [logs, setLogs] = useState<{ items: Record<string, unknown>[]; total: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch(`/admin/push-logs?page=${page}&page_size=20`)
      if (res.ok) setLogs(await res.json())
    } finally {
      setLoading(false)
    }
  }, [page])

  useEffect(() => { fetchLogs() }, [fetchLogs])

  if (loading) return <Loading />

  return (
    <div className="space-y-4">
      <div className="text-[13px] text-foreground/50">共 {logs?.total ?? 0} 条推送日志</div>
      <div className="space-y-2">
        {(logs?.items ?? []).map((log: Record<string, unknown>) => (
          <div
            key={log.id as number}
            className={cn(
              "flex items-start gap-3 p-3 rounded-xl border",
              v ? "border-accent/20 bg-accent/5" : "border-border bg-muted/20"
            )}
          >
            {log.status === "success"
              ? <CheckCircle size={14} className="text-green-500 shrink-0 mt-0.5" />
              : <AlertCircle size={14} className="text-red-400 shrink-0 mt-0.5" />
            }
            <div className="min-w-0">
              <div className="text-[13px] font-medium text-foreground/70">
                {(log.pushed_at as string)?.slice(0, 16)} · 任务 {(log.task_id as string)?.slice(0, 8)}...
              </div>
              {log.report_summary && (
                <div className="text-[12px] text-foreground/40 truncate">
                  {log.report_summary as string}
                </div>
              )}
              {log.error && (
                <div className="text-[12px] text-red-400 truncate">{log.error as string}</div>
              )}
            </div>
          </div>
        ))}
      </div>
      <PageControls page={page} total={logs?.total ?? 0} pageSize={20} onPage={setPage} v={v} />
    </div>
  )
}

// ── WCF Tab ─────────────────────────────────────────────────────

function WcfTab({ v }: { v: boolean }) {
  const [bindings, setBindings] = useState<Record<string, unknown>[]>([])
  const [loading, setLoading] = useState(true)
  const [broadcastMsg, setBroadcastMsg] = useState("")
  const [broadcasting, setBroadcasting] = useState(false)
  const [broadcastResult, setBroadcastResult] = useState<string | null>(null)

  useEffect(() => {
    apiFetch("/admin/wcf-bindings")
      .then((r) => r.json())
      .then(setBindings)
      .finally(() => setLoading(false))
  }, [])

  const broadcast = async () => {
    if (!broadcastMsg.trim()) return
    setBroadcasting(true)
    setBroadcastResult(null)
    try {
      const res = await apiFetch("/admin/broadcast", {
        method: "POST",
        body: JSON.stringify({ message: broadcastMsg }),
      })
      const data = await res.json()
      setBroadcastResult(`已发送 ${data.success} 人，失败 ${data.failed} 人`)
      setBroadcastMsg("")
    } finally {
      setBroadcasting(false)
    }
  }

  if (loading) return <Loading />

  return (
    <div className="space-y-6">
      {/* 广播 */}
      <div className={cn(
        "rounded-2xl border p-4 space-y-3",
        v ? "border-accent/20 bg-accent/5" : "border-border bg-muted/20"
      )}>
        <div className="text-[13px] font-medium">广播消息</div>
        <textarea
          value={broadcastMsg}
          onChange={(e) => setBroadcastMsg(e.target.value)}
          placeholder="向所有已启用联系人发送消息..."
          rows={3}
          className={cn(
            "w-full px-3 py-2 rounded-xl text-[13px] border outline-none resize-none",
            v ? "border-accent/30 bg-accent/5" : "border-border bg-muted/50"
          )}
        />
        <div className="flex items-center gap-3">
          <button
            onClick={broadcast}
            disabled={broadcasting || !broadcastMsg.trim()}
            className={cn(
              "px-4 py-2 rounded-xl text-[13px] font-medium transition-all",
              v ? "bg-accent text-white hover:bg-accent/90" : "bg-foreground text-background hover:bg-foreground/90",
              (broadcasting || !broadcastMsg.trim()) && "opacity-50 cursor-not-allowed"
            )}
          >
            {broadcasting ? "发送中..." : "发送"}
          </button>
          {broadcastResult && <span className="text-[12px] text-foreground/50">{broadcastResult}</span>}
        </div>
      </div>

      {/* 绑定列表 */}
      <div className="space-y-2">
        <div className="text-[13px] text-foreground/50">共 {bindings.length} 个绑定联系人</div>
        {bindings.map((b: Record<string, unknown>) => (
          <div
            key={b.id as string}
            className={cn(
              "flex items-center justify-between p-3 rounded-xl border",
              v ? "border-accent/20 bg-accent/5" : "border-border bg-muted/20"
            )}
          >
            <div>
              <div className="text-[13px] font-medium">{b.user_id as string}</div>
              <div className="text-[12px] text-foreground/40">
                账号：{b.account_id as string} · 最后消息：{b.last_message as string || "无"}
              </div>
            </div>
            <span className={cn(
              "text-[11px] px-2 py-0.5 rounded-full",
              b.enabled ? "bg-green-500/10 text-green-600" : "bg-foreground/10 text-foreground/40"
            )}>
              {b.enabled ? "已启用" : "已禁用"}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── RSS Tab ──────────────────────────────────────────────────────

function RssTab({ v }: { v: boolean }) {
  const [feeds, setFeeds] = useState<{ items: Record<string, unknown>[]; total: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)

  const fetchFeeds = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch(`/admin/rss-feeds?page=${page}&page_size=30`)
      if (res.ok) setFeeds(await res.json())
    } finally {
      setLoading(false)
    }
  }, [page])

  useEffect(() => { fetchFeeds() }, [fetchFeeds])

  if (loading) return <Loading />

  return (
    <div className="space-y-4">
      <div className="text-[13px] text-foreground/50">共 {feeds?.total ?? 0} 个 RSS 源</div>
      <div className="space-y-2">
        {(feeds?.items ?? []).map((f: Record<string, unknown>) => (
          <div
            key={f.id as string}
            className={cn(
              "flex items-center justify-between p-3 rounded-xl border",
              v ? "border-accent/20 bg-accent/5" : "border-border bg-muted/20"
            )}
          >
            <div className="min-w-0">
              <div className="text-[13px] font-medium truncate">{f.name as string}</div>
              <div className="text-[12px] text-foreground/40 truncate">{f.url as string}</div>
            </div>
            <span className={cn(
              "text-[11px] px-2 py-0.5 rounded-full shrink-0 ml-2",
              f.enabled ? "bg-green-500/10 text-green-600" : "bg-foreground/10 text-foreground/40"
            )}>
              {f.enabled ? "启用" : "停用"}
            </span>
          </div>
        ))}
      </div>
      <PageControls page={page} total={feeds?.total ?? 0} pageSize={30} onPage={setPage} v={v} />
    </div>
  )
}

// ── Shared ────────────────────────────────────────────────────────

function PageControls({ page, total, pageSize, onPage, v }: {
  page: number; total: number; pageSize: number; onPage: (p: number) => void; v: boolean
}) {
  const totalPages = Math.ceil(total / pageSize)
  if (totalPages <= 1) return null

  return (
    <div className="flex items-center gap-2 justify-center">
      <button
        onClick={() => onPage(page - 1)}
        disabled={page <= 1}
        className={cn(
          "px-3 py-1.5 rounded-lg text-[13px] border transition-all",
          v ? "border-accent/30 hover:bg-accent/10" : "border-border hover:bg-muted",
          page <= 1 && "opacity-40 cursor-not-allowed"
        )}
      >
        上一页
      </button>
      <span className="text-[13px] text-foreground/50">{page} / {totalPages}</span>
      <button
        onClick={() => onPage(page + 1)}
        disabled={page >= totalPages}
        className={cn(
          "px-3 py-1.5 rounded-lg text-[13px] border transition-all",
          v ? "border-accent/30 hover:bg-accent/10" : "border-border hover:bg-muted",
          page >= totalPages && "opacity-40 cursor-not-allowed"
        )}
      >
        下一页
      </button>
    </div>
  )
}

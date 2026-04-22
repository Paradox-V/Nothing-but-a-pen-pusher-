import { useState, useEffect, useRef } from "react"
import { Smartphone, ChevronDown, ChevronRight, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

import { apiFetch } from "@/hooks/use-api"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import type { WcfAccount, WcfBinding, MonitorTask, PushLog } from "./types"
import { ContactCard } from "./ContactCard"

interface WechatAccountSectionProps {
  wcfAccounts: WcfAccount[]
  wcfBindings: WcfBinding[]
  tasks: MonitorTask[]
  expandedTask: string | null
  logs: PushLog[]
  onLoadAccounts: () => void
  onLoadBindings: () => void
  onLoadTasks: () => void
  onRunTask: (taskId: string) => void
  onDeleteTask: (taskId: string) => void
  onToggleExpandTask: (taskId: string | null) => void
  runningTaskId: string | null
}

export function WechatAccountSection({
  wcfAccounts, wcfBindings, tasks, expandedTask, logs,
  onLoadAccounts, onLoadBindings, onLoadTasks,
  onRunTask, onDeleteTask, onToggleExpandTask, runningTaskId,
}: WechatAccountSectionProps) {
  const [showQRDialog, setShowQRDialog] = useState(false)
  const [qrImageUrl, setQrImageUrl] = useState<string | null>(null)
  const [loginStatus, setLoginStatus] = useState<string>("idle")
  const [loginError, setLoginError] = useState<string>("")
  const [expandedAccounts, setExpandedAccounts] = useState<Set<string>>(new Set())
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const startLogin = async () => {
    setLoginStatus("loading")
    setLoginError("")
    setQrImageUrl(null)
    try {
      const res = await apiFetch("/wcf/login/start", { method: "POST" })
      if (!res.ok) throw new Error("登录请求失败")
      const data = await res.json()
      const sessionId = data.session_id
      if (!sessionId) throw new Error("未获取到 session_id")

      const qrRes = await apiFetch(`/wcf/login/qr?session_id=${sessionId}`)
      if (!qrRes.ok) throw new Error("二维码获取失败")
      const blob = await qrRes.blob()
      const url = URL.createObjectURL(blob)
      setQrImageUrl(url)
      setLoginStatus("polling")

      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(async () => {
        try {
          const statusRes = await apiFetch(`/wcf/login/status?session_id=${sessionId}`)
          if (!statusRes.ok) return
          const statusData = await statusRes.json()
          if (statusData.status === "confirmed") {
            if (pollRef.current) clearInterval(pollRef.current)
            setLoginStatus("success")
            onLoadAccounts()
            setTimeout(() => {
              setShowQRDialog(false)
              setLoginStatus("idle")
              if (qrImageUrl) URL.revokeObjectURL(qrImageUrl)
            }, 1500)
          }
        } catch { /* keep polling */ }
      }, 2000)
    } catch (e: any) {
      setLoginStatus("error")
      setLoginError(e.message || "登录失败")
    }
  }

  const closeQRDialog = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (qrImageUrl) URL.revokeObjectURL(qrImageUrl)
    setQrImageUrl(null)
    setShowQRDialog(false)
    setLoginStatus("idle")
  }

  const toggleAccount = (accountId: string) => {
    setExpandedAccounts((prev) => {
      const next = new Set(prev)
      if (next.has(accountId)) next.delete(accountId)
      else next.add(accountId)
      return next
    })
  }

  const createTaskAndBind = async (bindingId: string, name: string, keywords: string[], schedule: string) => {
    try {
      const res = await apiFetch("/monitor/tasks", {
        method: "POST",
        body: JSON.stringify({ name, keywords, schedule, push_config: [{ type: "wcf" }] }),
      })
      if (!res.ok) return
      const task = await res.json()
      await apiFetch(`/wcf/bindings/${bindingId}/tasks`, {
        method: "POST",
        body: JSON.stringify({ task_id: task.id }),
      })
      onLoadTasks()
      onLoadBindings()
    } catch { /* */ }
  }

  const unbindTask = async (bindingId: string, taskId: string) => {
    await apiFetch(`/wcf/bindings/${bindingId}/tasks/${taskId}`, { method: "DELETE" })
    onLoadBindings()
    onLoadTasks()
  }

  const toggleBindingEnabled = async (bindingId: string, enabled: boolean) => {
    await apiFetch(`/wcf/bindings/${bindingId}`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    })
    onLoadBindings()
  }

  const wcfConnected = wcfAccounts.length > 0

  // Group bindings by account
  const bindingsByAccount = wcfBindings.reduce<Record<string, WcfBinding[]>>((acc, b) => {
    if (!acc[b.account_id]) acc[b.account_id] = []
    acc[b.account_id].push(b)
    return acc
  }, {})

  return (
    <div className="mb-6">
      {/* Connection status card */}
      <div className={cn("p-4 rounded-2xl border", "bg-card border-accent/10")}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn("p-2 rounded-xl", "bg-accent/10")}>
              <Smartphone size={18} className={"text-accent"} />
            </div>
            <div>
              <h3 className={cn("text-sm font-medium", "text-foreground")}>
                微信账号管理
              </h3>
              <p className="text-xs text-foreground/40">
                {wcfConnected
                  ? `已连接 ${wcfAccounts.length} 个账号`
                  : "未连接 — 扫码登录个人微信"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {wcfAccounts.map(a => (
              <span key={a.account_id} className="px-2 py-1 rounded-lg text-xs bg-green-500/10 text-green-500">
                {a.account_id.split("@")[0]}
              </span>
            ))}
            <button onClick={() => { setShowQRDialog(true); startLogin() }}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-medium",
                "bg-accent text-accent-foreground hover:bg-accent/80"
              )}>
              + 添加微信
            </button>
          </div>
        </div>
      </div>

      {/* QR Dialog */}
      <Dialog open={showQRDialog} onOpenChange={(open: boolean) => { if (!open) closeQRDialog() }}>
        <DialogContent showCloseButton={true}>
          <DialogHeader>
            <DialogTitle>扫码登录微信</DialogTitle>
            <DialogDescription>请使用微信扫描下方二维码</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col items-center gap-4 py-4">
            {loginStatus === "loading" && (
              <div className="flex flex-col items-center gap-2">
                <Loader2 size={32} className="animate-spin text-foreground/30" />
                <p className="text-xs text-foreground/40">正在获取二维码...</p>
              </div>
            )}
            {loginStatus === "polling" && qrImageUrl && (
              <div className="flex flex-col items-center gap-2">
                <img src={qrImageUrl} alt="微信登录二维码" className="w-48 h-48 rounded-lg" />
                <p className="text-xs text-foreground/40">等待扫码确认...</p>
              </div>
            )}
            {loginStatus === "success" && (
              <div className="flex flex-col items-center gap-2">
                <span className="text-green-500 text-2xl">✓</span>
                <p className="text-xs text-green-500">登录成功！</p>
              </div>
            )}
            {loginStatus === "error" && (
              <div className="flex flex-col items-center gap-2">
                <p className="text-xs text-red-400">{loginError}</p>
                <button onClick={startLogin}
                  className="px-3 py-1.5 rounded-lg text-xs bg-muted border border-border hover:bg-muted/80">重试</button>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Per-account contact lists */}
      {wcfConnected && Object.entries(bindingsByAccount).map(([accountId, bindings]) => {
        const isExpanded = expandedAccounts.has(accountId)
        const account = wcfAccounts.find(a => a.account_id === accountId)
        return (
          <div key={accountId} className={cn("mt-3 rounded-2xl border overflow-hidden",
            "bg-card border-accent/10"
          )}>
            <button
              onClick={() => toggleAccount(accountId)}
              className={cn("w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-muted/30 transition-all",
                "text-foreground"
              )}
            >
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <span className="text-sm font-medium">{accountId.split("@")[0]}</span>
              <span className="text-[10px] text-foreground/30">{bindings.length} 个联系人</span>
              {account && (
                <span className="ml-auto px-1.5 py-0.5 rounded text-[10px] bg-green-500/10 text-green-500">已连接</span>
              )}
            </button>
            {isExpanded && (
              <div className="px-4 pb-3 space-y-2">
                {bindings.map(b => (
                  <ContactCard
                    key={b.id}
                    binding={b}
                    tasks={tasks}
                    expandedTask={expandedTask}
                    logs={logs}
                    onCreateTask={(name, keywords, schedule) => createTaskAndBind(b.id, name, keywords, schedule)}
                    onUnbindTask={(taskId) => unbindTask(b.id, taskId)}
                    onToggleEnabled={() => toggleBindingEnabled(b.id, !b.enabled)}
                    onToggleExpandTask={onToggleExpandTask}
                    onRunTask={onRunTask}
                    onDeleteTask={onDeleteTask}
                    runningTaskId={runningTaskId}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

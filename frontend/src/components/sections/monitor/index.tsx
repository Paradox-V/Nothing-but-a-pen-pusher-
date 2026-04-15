import { useState, useEffect, useCallback, useRef } from "react"
import { cn } from "@/lib/utils"
import { useTheme } from "@/hooks/use-theme"
import { apiFetch } from "@/hooks/use-api"
import type { MonitorTask, PushLog, WcfAccount, WcfBinding } from "./types"
import { isWcfTask } from "./types"
import { WechatAccountSection } from "./WechatAccountSection"
import { NonWcfTaskSection } from "./NonWcfTaskSection"

export function MonitorPanel() {
  const [tasks, setTasks] = useState<MonitorTask[]>([])
  const [logs, setLogs] = useState<PushLog[]>([])
  const [expandedTask, setExpandedTask] = useState<string | null>(null)

  // WCF state
  const [wcfAccounts, setWcfAccounts] = useState<WcfAccount[]>([])
  const [wcfBindings, setWcfBindings] = useState<WcfBinding[]>([])

  const { theme } = useTheme()
  const v = theme === "vintage"

  useEffect(() => { loadTasks() }, [])
  useEffect(() => { loadWcfAccounts() }, [])
  useEffect(() => { loadWcfBindings() }, [])

  const loadTasks = async () => {
    try {
      const res = await apiFetch("/monitor/tasks")
      if (res.ok) {
        const data = await res.json()
        setTasks(Array.isArray(data) ? data : [])
      }
    } catch { /* */ }
  }

  const loadLogs = async (taskId: string) => {
    try {
      const res = await apiFetch(`/monitor/tasks/${taskId}/logs`)
      if (res.ok) {
        const data = await res.json()
        setLogs(Array.isArray(data) ? data : [])
      }
    } catch { /* */ }
  }

  const loadWcfAccounts = useCallback(async () => {
    try {
      const res = await apiFetch("/wcf/accounts")
      if (res.ok) {
        const data = await res.json()
        setWcfAccounts(data.items || [])
      }
    } catch { /* */ }
  }, [])

  const loadWcfBindings = useCallback(async () => {
    try {
      const res = await apiFetch("/wcf/bindings")
      if (res.ok) {
        const data = await res.json()
        setWcfBindings(Array.isArray(data) ? data : [])
      }
    } catch { /* */ }
  }, [])

  const [runningTaskId, setRunningTaskId] = useState<string | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const fallbackRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 组件卸载时清理轮询
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
      if (fallbackRef.current) clearTimeout(fallbackRef.current)
    }
  }, [])

  const runTask = async (id: string) => {
    if (runningTaskId === id) return // 防重复点击
    setRunningTaskId(id)
    try {
      const res = await apiFetch(`/monitor/tasks/${id}/run`, { method: "POST" })
      if (res.status === 409) {
        const data = await res.json().catch(() => ({}))
        alert(data.reason || "任务正在执行中")
        setRunningTaskId(null)
        return
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        alert(`执行失败: ${data.error || res.status}`)
        setRunningTaskId(null)
        return
      }

      // 清理已有的轮询
      if (pollingRef.current) clearInterval(pollingRef.current)
      if (fallbackRef.current) clearTimeout(fallbackRef.current)

      // 轮询等待任务完成（每 5 秒检查 task 的 last_run_at）
      pollingRef.current = setInterval(async () => {
        try {
          const taskRes = await apiFetch(`/monitor/tasks/${id}`)
          if (!taskRes.ok) return
          const taskData = await taskRes.json()
          const lastRun = new Date(taskData.last_run_at).getTime()
          // last_run_at 在 30 秒内 → 任务刚完成
          if (Date.now() - lastRun < 30000) {
            loadTasks()
            if (expandedTask === id) loadLogs(id)
            clearInterval(pollingRef.current!)
            pollingRef.current = null
            if (fallbackRef.current) {
              clearTimeout(fallbackRef.current)
              fallbackRef.current = null
            }
            setRunningTaskId(null)
          }
        } catch { /* 轮询忽略网络错误 */ }
      }, 5000)

      // 兜底：60 秒后强制结束轮询
      fallbackRef.current = setTimeout(() => {
        if (pollingRef.current) clearInterval(pollingRef.current)
        pollingRef.current = null
        fallbackRef.current = null
        setRunningTaskId(null)
        loadTasks()
      }, 60000)
    } catch (err) {
      alert(`请求失败: ${err}`)
      setRunningTaskId(null)
    }
  }

  const deleteTask = async (id: string) => {
    await apiFetch(`/monitor/tasks/${id}`, { method: "DELETE" })
    loadTasks()
    if (expandedTask === id) setExpandedTask(null)
  }

  const toggleExpand = (taskId: string | null) => {
    if (expandedTask === taskId) {
      setExpandedTask(null)
    } else {
      setExpandedTask(taskId)
      if (taskId) loadLogs(taskId)
    }
  }

  // Split tasks
  const nonWcfTasks = tasks.filter((t) => !isWcfTask(t))

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <div className="mb-6">
        <h2 className={cn("text-2xl font-bold", v ? "text-[#2C2E31]" : "text-foreground")}>定时监控</h2>
        <p className="text-sm text-foreground/40 mt-1">设置关键词监控任务，Agent 自动收集并定时推送报告</p>
      </div>

      <WechatAccountSection
        wcfAccounts={wcfAccounts}
        wcfBindings={wcfBindings}
        tasks={tasks}
        expandedTask={expandedTask}
        logs={logs}
        v={v}
        onLoadAccounts={loadWcfAccounts}
        onLoadBindings={loadWcfBindings}
        onLoadTasks={loadTasks}
        onRunTask={runTask}
        onDeleteTask={deleteTask}
        onToggleExpandTask={toggleExpand}
        runningTaskId={runningTaskId}
      />

      <NonWcfTaskSection
        tasks={nonWcfTasks}
        expandedTask={expandedTask}
        logs={logs}
        v={v}
        onLoadTasks={loadTasks}
        onToggleExpandTask={toggleExpand}
        onRunTask={runTask}
        onDeleteTask={deleteTask}
      />
    </div>
  )
}

import { useState, useEffect, useCallback } from "react"
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

  const runTask = async (id: string) => {
    await apiFetch(`/monitor/tasks/${id}/run`, { method: "POST" })
    loadTasks()
    if (expandedTask === id) loadLogs(id)
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

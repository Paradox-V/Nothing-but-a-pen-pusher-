import { useState } from "react"
import { motion } from "framer-motion"
import { Plus, Play, Trash2, Clock, Tag, Settings2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { apiFetch } from "@/hooks/use-api"
import { Empty } from "@/components/shared/Empty"
import type { MonitorTask, PushLog } from "./types"
import { SCHEDULE_OPTIONS, NON_WCF_CHANNEL_TYPES, CHANNEL_HINTS } from "./types"

interface NonWcfTaskSectionProps {
  tasks: MonitorTask[]
  expandedTask: string | null
  logs: PushLog[]
  v: boolean
  onLoadTasks: () => void
  onToggleExpandTask: (taskId: string | null) => void
  onRunTask: (taskId: string) => void
  onDeleteTask: (taskId: string) => void
}

export function NonWcfTaskSection({
  tasks, expandedTask, logs, v,
  onLoadTasks, onToggleExpandTask, onRunTask, onDeleteTask,
}: NonWcfTaskSectionProps) {
  const [showCreate, setShowCreate] = useState(false)
  const [formName, setFormName] = useState("")
  const [formKeywords, setFormKeywords] = useState("")
  const [formSchedule, setFormSchedule] = useState("daily_morning")
  const [formChannelType, setFormChannelType] = useState("wecom")
  const [formChannelUrl, setFormChannelUrl] = useState("")
  const [formChannelSecret, setFormChannelSecret] = useState("")

  const createTask = async () => {
    if (!formName || !formKeywords) return
    try {
      const res = await apiFetch("/monitor/tasks", {
        method: "POST",
        body: JSON.stringify({
          name: formName,
          keywords: formKeywords.split(",").map((k) => k.trim()).filter(Boolean),
          schedule: formSchedule,
          push_config: [{ type: formChannelType, url: formChannelUrl, secret: formChannelSecret }],
        }),
      })
      if (res.ok) {
        setShowCreate(false)
        setFormName(""); setFormKeywords(""); setFormChannelUrl(""); setFormChannelSecret("")
        onLoadTasks()
      }
    } catch { /* */ }
  }

  const testPush = async () => {
    if (!formChannelUrl) return
    await apiFetch("/monitor/test-push", {
      method: "POST",
      body: JSON.stringify({ push_config: [{ type: formChannelType, url: formChannelUrl, secret: formChannelSecret }] }),
    })
  }

  const getChannelLabel = (task: MonitorTask): string => {
    try {
      const config = JSON.parse(task.push_config)
      const ch = NON_WCF_CHANNEL_TYPES.find(c => c.value === config?.[0]?.type)
      return ch?.label || config?.[0]?.type || ""
    } catch { return "" }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className={cn("text-sm font-medium", v ? "text-[#2C2E31]" : "text-foreground")}>
          其他推送渠道
        </h3>
        <button onClick={() => setShowCreate(!showCreate)}
          className={cn("flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
            v ? "bg-[#4F7942] text-white hover:bg-[#3B5E32]" : "bg-accent text-accent-foreground hover:bg-accent/90"
          )}
        ><Plus size={13} /> 新建任务</button>
      </div>

      {/* Create form */}
      {showCreate && (
        <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
          className={cn("mb-4 p-4 rounded-2xl border space-y-3",
            v ? "bg-[#E8E9E4] border-[#4F7942]/20" : "bg-card border-border"
          )}
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-foreground/50 mb-1 block">任务名称</label>
              <input value={formName} onChange={(e) => setFormName(e.target.value)}
                placeholder="如：AI行业动态"
                className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-accent/30" />
            </div>
            <div>
              <label className="text-xs text-foreground/50 mb-1 block">推送时间</label>
              <select value={formSchedule} onChange={(e) => setFormSchedule(e.target.value)}
                className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground focus:outline-none">
                {SCHEDULE_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-foreground/50 mb-1 block">关键词（逗号分隔）</label>
            <input value={formKeywords} onChange={(e) => setFormKeywords(e.target.value)}
              placeholder="如：AI大模型，半导体，芯片"
              className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-accent/30" />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-foreground/50 mb-1 block">推送渠道</label>
              <select value={formChannelType} onChange={(e) => setFormChannelType(e.target.value)}
                className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground focus:outline-none">
                {NON_WCF_CHANNEL_TYPES.map((ct) => <option key={ct.value} value={ct.value}>{ct.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-foreground/50 mb-1 block">
                {formChannelType === "telegram" ? "Bot Token" : "URL"}
              </label>
              <input value={formChannelUrl} onChange={(e) => setFormChannelUrl(e.target.value)}
                placeholder={CHANNEL_HINTS[formChannelType]?.url || "Webhook URL"}
                className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-accent/30" />
            </div>
            <div>
              <label className="text-xs text-foreground/50 mb-1 block">
                {CHANNEL_HINTS[formChannelType]?.secret ? "Secret" : "Secret（可选）"}
              </label>
              <input value={formChannelSecret} onChange={(e) => setFormChannelSecret(e.target.value)}
                placeholder={CHANNEL_HINTS[formChannelType]?.secret || "可选"}
                className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-accent/30" />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={createTask}
              className={cn("px-4 py-2 rounded-lg text-sm font-medium",
                v ? "bg-[#4F7942] text-white hover:bg-[#3B5E32]" : "bg-accent text-accent-foreground hover:bg-accent/90"
              )}>创建任务</button>
            <button onClick={testPush}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-muted text-foreground/60 hover:text-foreground/80 border border-border">测试推送</button>
            <button onClick={() => setShowCreate(false)}
              className="px-4 py-2 rounded-lg text-sm text-foreground/40 hover:text-foreground/60">取消</button>
          </div>
        </motion.div>
      )}

      {/* Task list */}
      {tasks.length === 0 ? (
        <Empty icon={<Settings2 size={40} />} title="暂无其他推送任务" description="创建企业微信、钉钉、飞书等渠道的推送任务" />
      ) : (
        <div className="space-y-3">
          {tasks.map((task) => (
            <div key={task.id}
              className={cn("rounded-2xl border overflow-hidden transition-all",
                v ? "bg-[#E8E9E4] border-[#4F7942]/10" : "bg-card border-border"
              )}
            >
              <div className="flex items-center gap-3 px-5 py-4 cursor-pointer" onClick={() => onToggleExpandTask(task.id)}>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{task.name}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-accent/10 text-accent">
                      {getChannelLabel(task)}
                    </span>
                    {task.is_active ? (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-500/10 text-green-500">运行中</span>
                    ) : (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-foreground/10 text-foreground/40">已暂停</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-1.5 text-xs text-foreground/40">
                    <span className="flex items-center gap-1"><Tag size={10} /> {(task.keywords as unknown as string[])?.join("、")}</span>
                    <span className="flex items-center gap-1"><Clock size={10} /> {SCHEDULE_OPTIONS.find((o) => o.value === task.schedule)?.label || task.schedule}</span>
                    {task.last_run_at && <span>上次推送: {task.last_run_at}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={(e) => { e.stopPropagation(); onRunTask(task.id) }}
                    className="p-2 rounded-lg hover:bg-muted text-foreground/30 hover:text-foreground/60 transition-all" title="立即执行"
                  ><Play size={14} /></button>
                  <button onClick={(e) => { e.stopPropagation(); onDeleteTask(task.id) }}
                    className="p-2 rounded-lg hover:bg-muted text-foreground/30 hover:text-destructive transition-all" title="删除"
                  ><Trash2 size={14} /></button>
                </div>
              </div>

              {expandedTask === task.id && (
                <div className="px-5 pb-4 border-t border-border/30">
                  <h4 className="text-xs font-medium text-foreground/50 mt-3 mb-2">推送日志</h4>
                  {logs.length === 0 ? (
                    <p className="text-xs text-foreground/30">暂无推送记录</p>
                  ) : (
                    <div className="space-y-2">
                      {logs.map((log) => (
                        <div key={log.id} className="text-xs p-2 rounded-lg bg-muted/50">
                          <div className="flex items-center gap-2">
                            <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold",
                              log.status === "success" ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"
                            )}>{log.status}</span>
                            <span className="text-foreground/40">{log.pushed_at}</span>
                          </div>
                          {log.report_summary && (
                            <p className="mt-1 text-foreground/50 line-clamp-2">{log.report_summary}</p>
                          )}
                          {log.error && (
                            <p className="mt-1 text-red-400">{log.error}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

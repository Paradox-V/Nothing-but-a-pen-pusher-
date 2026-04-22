import { useState } from "react"
import { Unlink, Plus, Play, Trash2, Clock, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

import type { WcfBinding, MonitorTask, PushLog } from "./types"
import { formatSchedule } from "./types"
import { InlineTaskForm } from "./InlineTaskForm"

interface ContactCardProps {
  binding: WcfBinding
  tasks: MonitorTask[]
  expandedTask: string | null
  logs: PushLog[]
  onCreateTask: (name: string, keywords: string[], schedule: string) => void
  onUnbindTask: (taskId: string) => void
  onToggleEnabled: () => void
  onToggleExpandTask: (taskId: string) => void
  onRunTask: (taskId: string) => void
  onDeleteTask: (taskId: string) => void
  runningTaskId: string | null
}

export function ContactCard({
  binding, tasks, expandedTask, logs,
  onCreateTask, onUnbindTask, onToggleEnabled,
  onToggleExpandTask, onRunTask, onDeleteTask, runningTaskId,
}: ContactCardProps) {
  const [showForm, setShowForm] = useState(false)

  const boundTasks = binding.task_ids
    .map((tid) => tasks.find((t) => t.id === tid))
    .filter(Boolean) as MonitorTask[]

  return (
    <div className={cn("p-3 rounded-xl", "bg-muted/50")}>
      {/* Contact header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium truncate">
              {binding.display_name || binding.user_id.split("@")[0]}
            </span>
            <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold",
              binding.enabled ? "bg-green-500/10 text-green-500" : "bg-foreground/10 text-foreground/40"
            )}>{binding.enabled ? "已启用" : "未启用"}</span>
          </div>
          <p className="text-xs text-foreground/30 truncate mt-0.5">
            {binding.last_message || "暂无消息"}
            {binding.last_seen_at && <span> · {binding.last_seen_at}</span>}
          </p>
        </div>
        <button onClick={onToggleEnabled}
          className={cn("px-2 py-1 rounded-lg text-xs font-medium border transition-all shrink-0",
            binding.enabled
              ? "border-red-200 text-red-400 hover:bg-red-500/10"
              : "border-green-200 text-green-500 hover:bg-green-500/10"
          )}>
          {binding.enabled ? "禁用" : "启用"}
        </button>
      </div>

      {/* Bound tasks */}
      {binding.enabled && (
        <div className="mt-2">
          {boundTasks.length > 0 ? (
            <div className="space-y-1">
              {boundTasks.map((task) => (
                <div key={task.id} className="group">
                  <div
                    className={cn("flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer transition-all",
                      expandedTask === task.id
                        ? "bg-accent/10"
                        : "hover:bg-muted/80"
                    )}
                    onClick={() => onToggleExpandTask(task.id)}
                  >
                    <div className="flex-1 min-w-0">
                      <span className="text-xs font-medium">{task.name}</span>
                      <div className="flex items-center gap-2 mt-0.5 text-[10px] text-foreground/30">
                        <span className="flex items-center gap-0.5"><Clock size={8} />
                          {formatSchedule(task.schedule)}
                        </span>
                        {task.last_run_at && <span>上次: {task.last_run_at}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button onClick={(e) => { e.stopPropagation(); onRunTask(task.id) }}
                        className="p-1 rounded hover:bg-muted text-foreground/30 hover:text-foreground/60" title="立即执行"
                      >{runningTaskId === task.id ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}</button>
                      <button onClick={(e) => { e.stopPropagation(); onDeleteTask(task.id) }}
                        className="p-1 rounded hover:bg-muted text-foreground/30 hover:text-destructive" title="删除"
                      ><Trash2 size={12} /></button>
                      <button onClick={(e) => { e.stopPropagation(); onUnbindTask(task.id) }}
                        className="p-1 rounded hover:bg-muted text-foreground/30 hover:text-orange-400" title="取消绑定"
                      ><Unlink size={10} /></button>
                    </div>
                  </div>

                  {/* Expanded logs */}
                  {expandedTask === task.id && (
                    <div className="px-2.5 pb-2 pt-1">
                      {logs.length === 0 ? (
                        <p className="text-[10px] text-foreground/30">暂无推送记录</p>
                      ) : (
                        <div className="space-y-1">
                          {logs.map((log) => (
                            <div key={log.id} className="text-[10px] p-1.5 rounded-lg bg-muted/50">
                              <div className="flex items-center gap-1.5">
                                <span className={cn("px-1 py-0.5 rounded text-[9px] font-bold",
                                  log.status === "success" ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"
                                )}>{log.status}</span>
                                <span className="text-foreground/40">{log.pushed_at}</span>
                              </div>
                              {log.report_summary && (
                                <p className="mt-0.5 text-foreground/50 line-clamp-2">{log.report_summary}</p>
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
          ) : (
            <p className="text-[10px] text-foreground/30 mt-1">暂无推送任务</p>
          )}

          {/* Add task button / form */}
          {showForm ? (
            <InlineTaskForm
              onSubmit={onCreateTask}
              onCancel={() => setShowForm(false)}
            />
          ) : (
            <button onClick={() => setShowForm(true)}
              className="flex items-center gap-1 mt-1.5 px-2 py-1 rounded-lg text-[10px] text-foreground/40 hover:text-foreground/60 hover:bg-muted/50 transition-all">
              <Plus size={10} /> 新建推送任务
            </button>
          )}
        </div>
      )}
    </div>
  )
}

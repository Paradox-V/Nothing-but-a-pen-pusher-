import { useState } from "react"
import { cn } from "@/lib/utils"

import { Dropdown } from "@/components/shared/Dropdown"
import { SCHEDULE_DEFAULTS } from "./types"

interface InlineTaskFormProps {
  onSubmit: (name: string, keywords: string[], schedule: string) => void
  onCancel: () => void
}

export function InlineTaskForm({ onSubmit, onCancel }: InlineTaskFormProps) {
  const [name, setName] = useState("")
  const [keywords, setKeywords] = useState("")
  const [schedule, setSchedule] = useState("08:00")

  const handleSubmit = () => {
    if (!name || !keywords) return
    onSubmit(
      name,
      keywords.split(",").map((k) => k.trim()).filter(Boolean),
      schedule,
    )
  }

  return (
    <div className={cn("mt-2 p-3 rounded-xl border space-y-2",
      "bg-muted/30 border-accent/10"
    )}>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[10px] text-foreground/40 mb-0.5 block">任务名称</label>
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="如：AI行业动态"
            className="w-full px-2.5 py-1.5 bg-muted border border-border rounded-lg text-xs text-foreground focus:outline-none focus:border-accent/30" />
        </div>
        <div>
          <label className="text-[10px] text-foreground/40 mb-0.5 block">推送时间</label>
          <Dropdown value={schedule} onChange={setSchedule}
            options={SCHEDULE_DEFAULTS.map(t => ({ value: t, label: t }))} className="text-xs" />
        </div>
      </div>
      <div>
        <label className="text-[10px] text-foreground/40 mb-0.5 block">关键词（逗号分隔）</label>
        <input value={keywords} onChange={(e) => setKeywords(e.target.value)}
          placeholder="如：AI大模型，半导体，芯片"
          className="w-full px-2.5 py-1.5 bg-muted border border-border rounded-lg text-xs text-foreground focus:outline-none focus:border-accent/30" />
      </div>
      <div className="flex items-center gap-2">
        <button onClick={handleSubmit}
          className={cn("px-3 py-1.5 rounded-lg text-xs font-medium",
            "bg-accent text-accent-foreground hover:bg-accent/80"
          )}>创建</button>
        <button onClick={onCancel}
          className="px-3 py-1.5 rounded-lg text-xs text-foreground/40 hover:text-foreground/60">取消</button>
      </div>
    </div>
  )
}

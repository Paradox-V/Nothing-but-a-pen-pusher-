export interface MonitorTask {
  id: string
  name: string
  keywords: string[]
  filters?: Record<string, string>
  schedule: string
  push_config: string
  is_active: number
  last_run_at: string | null
  created_at: string
}

export interface PushLog {
  id: number
  task_id: string
  status: string
  report_summary: string | null
  error: string | null
  pushed_at: string
}

export interface WcfAccount {
  account_id: string
  login_status: string
  enabled: boolean
  last_inbound_at?: string
}

export interface WcfBinding {
  id: string
  account_id: string
  user_id: string
  display_name: string
  enabled: number
  last_seen_at: string | null
  last_message: string | null
  task_ids: string[]
}

export const SCHEDULE_DEFAULTS = [
  "08:00", "09:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00", "22:00",
]

export function formatSchedule(schedule: string): string {
  if (/^\d{2}:\d{2}$/.test(schedule)) {
    return `每日 ${schedule}`
  }
  // 兼容旧格式
  const legacy: Record<string, string> = {
    daily_morning: "每日 08:00",
    daily_evening: "每日 20:00",
  }
  return legacy[schedule] || schedule
}

export const NON_WCF_CHANNEL_TYPES = [
  { value: "wecom", label: "企业微信" },
  { value: "feishu", label: "飞书" },
  { value: "dingtalk", label: "钉钉" },
  { value: "discord", label: "Discord" },
  { value: "telegram", label: "Telegram Bot" },
  { value: "generic", label: "通用 Webhook" },
]

export const CHANNEL_HINTS: Record<string, { url: string; secret: string }> = {
  wecom:    { url: "Webhook 地址 (qyapi.weixin.qq.com/...)", secret: "" },
  dingtalk: { url: "Webhook 地址 (oapi.dingtalk.com/...)", secret: "签名密钥 (可选)" },
  feishu:   { url: "Webhook 地址 (open.feishu.cn/...)", secret: "" },
  telegram: { url: "Bot Token", secret: "Chat ID" },
  discord:  { url: "Discord Webhook URL", secret: "" },
  generic:  { url: "Webhook URL", secret: "" },
}

export function isWcfTask(task: MonitorTask): boolean {
  try {
    const config = JSON.parse(task.push_config)
    return Array.isArray(config) && config.some((ch: { type: string }) => ch.type === "wcf")
  } catch {
    return false
  }
}

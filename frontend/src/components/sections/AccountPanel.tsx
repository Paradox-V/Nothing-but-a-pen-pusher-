import { useState } from "react"
import { motion } from "framer-motion"
import { LogIn, UserPlus, LogOut, Key, Mail, Shield } from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "@/hooks/use-theme"
import { useAuth } from "@/hooks/use-auth"

type Tab = "login" | "register" | "profile"

export function AccountPanel() {
  const { user, isAuthenticated, login, register, logout } = useAuth()
  const [tab, setTab] = useState<Tab>(isAuthenticated ? "profile" : "login")
  const { theme } = useTheme()
  const v = theme === "vintage"

  if (isAuthenticated && user) {
    return <ProfileView user={user} logout={logout} v={v} />
  }

  return (
    <div className="max-w-md mx-auto px-4 py-12">
      <div className="flex gap-2 mb-6">
        {(["login", "register"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "flex-1 py-2 rounded-xl text-[13px] font-medium transition-all",
              tab === t
                ? v ? "bg-accent text-white" : "bg-muted text-foreground"
                : "text-foreground/50 hover:text-foreground/80"
            )}
          >
            {t === "login" ? "登录" : "注册"}
          </button>
        ))}
      </div>
      {tab === "login" ? (
        <LoginForm login={login} v={v} />
      ) : (
        <RegisterForm register={register} v={v} />
      )}
    </div>
  )
}

function LoginForm({ login, v }: { login: (u: string, p: string) => Promise<void>; v: boolean }) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setLoading(true)
    try {
      await login(username, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <motion.form
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      onSubmit={handleSubmit}
      className="space-y-4"
    >
      <h2 className="text-lg font-semibold flex items-center gap-2">
        <LogIn size={18} className={v ? "text-accent" : "text-foreground/60"} />
        登录账号
      </h2>
      {error && (
        <div className="text-[13px] text-red-500 bg-red-500/10 rounded-lg px-3 py-2">
          {error}
        </div>
      )}
      <InputField label="用户名" value={username} onChange={setUsername} v={v} />
      <InputField label="密码" value={password} onChange={setPassword} type="password" v={v} />
      <button
        type="submit"
        disabled={loading}
        className={cn(
          "w-full py-2.5 rounded-xl text-[14px] font-medium transition-all",
          v ? "bg-accent text-white hover:bg-accent/90" : "bg-foreground text-background hover:bg-foreground/90",
          loading && "opacity-60 cursor-not-allowed"
        )}
      >
        {loading ? "登录中..." : "登录"}
      </button>
    </motion.form>
  )
}

function RegisterForm({
  register, v
}: { register: (u: string, p: string, e?: string, ic?: string) => Promise<void>; v: boolean }) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [email, setEmail] = useState("")
  const [inviteCode, setInviteCode] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setLoading(true)
    try {
      await register(username, password, email, inviteCode)
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <motion.form
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      onSubmit={handleSubmit}
      className="space-y-4"
    >
      <h2 className="text-lg font-semibold flex items-center gap-2">
        <UserPlus size={18} className={v ? "text-accent" : "text-foreground/60"} />
        注册账号
      </h2>
      {error && (
        <div className="text-[13px] text-red-500 bg-red-500/10 rounded-lg px-3 py-2">
          {error}
        </div>
      )}
      <InputField label="用户名" value={username} onChange={setUsername} v={v} />
      <InputField label="密码（至少8位，含字母和数字）" value={password} onChange={setPassword} type="password" v={v} />
      <InputField label="邮箱（可选）" value={email} onChange={setEmail} type="email" v={v} />
      <InputField label="邀请码（如未开放注册则必填）" value={inviteCode} onChange={setInviteCode} v={v} />
      <button
        type="submit"
        disabled={loading}
        className={cn(
          "w-full py-2.5 rounded-xl text-[14px] font-medium transition-all",
          v ? "bg-accent text-white hover:bg-accent/90" : "bg-foreground text-background hover:bg-foreground/90",
          loading && "opacity-60 cursor-not-allowed"
        )}
      >
        {loading ? "注册中..." : "注册"}
      </button>
    </motion.form>
  )
}

function ProfileView({
  user, logout, v
}: { user: { id: string; username: string; email: string; role: string }; logout: () => void; v: boolean }) {
  return (
    <div className="max-w-md mx-auto px-4 py-12 space-y-6">
      <div className={cn(
        "rounded-2xl border p-6 space-y-4",
        v ? "border-accent/20 bg-accent/5" : "border-border bg-muted/30"
      )}>
        <div className="flex items-center gap-3">
          <div className={cn(
            "w-12 h-12 rounded-full flex items-center justify-center text-lg font-bold",
            v ? "bg-accent text-white" : "bg-foreground/10 text-foreground"
          )}>
            {user.username[0].toUpperCase()}
          </div>
          <div>
            <div className="font-semibold text-[15px]">{user.username}</div>
            {user.role === "admin" && (
              <span className={cn(
                "text-[11px] px-2 py-0.5 rounded-full",
                v ? "bg-accent/20 text-accent" : "bg-foreground/10 text-foreground/60"
              )}>
                管理员
              </span>
            )}
          </div>
        </div>
        <div className="space-y-2 text-[13px] text-foreground/60">
          {user.email && (
            <div className="flex items-center gap-2">
              <Mail size={13} />
              <span>{user.email}</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <Shield size={13} />
            <span>角色：{user.role === "admin" ? "管理员" : "普通用户"}</span>
          </div>
          <div className="flex items-center gap-2">
            <Key size={13} />
            <span>用户 ID：{user.id.slice(0, 8)}...</span>
          </div>
        </div>
      </div>
      <button
        onClick={logout}
        className={cn(
          "w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-[14px] font-medium",
          "border border-border text-foreground/60 hover:text-foreground hover:border-foreground/40 transition-all"
        )}
      >
        <LogOut size={15} />
        退出登录
      </button>
    </div>
  )
}

function InputField({
  label, value, onChange, type = "text", v
}: { label: string; value: string; onChange: (v: string) => void; type?: string; v: boolean }) {
  return (
    <div className="space-y-1.5">
      <label className="text-[12px] text-foreground/50">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "w-full px-3 py-2 rounded-xl text-[14px] border outline-none transition-all",
          v
            ? "border-accent/30 bg-accent/5 focus:border-accent placeholder:text-foreground/30"
            : "border-border bg-muted/50 focus:border-foreground/40 placeholder:text-foreground/30"
        )}
      />
    </div>
  )
}

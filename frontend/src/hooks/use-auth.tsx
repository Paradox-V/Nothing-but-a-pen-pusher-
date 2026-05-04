import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react"
import { apiFetch } from "./use-api"

interface AuthUser {
  id: string
  username: string
  email: string
  role: string
}

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, email?: string, inviteCode?: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

const TOKEN_KEY = "_user_token"

function storeToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}
function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}
export function getUserToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(() => getUserToken())

  const logout = useCallback(() => {
    const t = getUserToken()
    if (t) {
      apiFetch("/account/logout", { method: "POST" }).catch(() => {})
    }
    clearToken()
    setToken(null)
    setUser(null)
  }, [])

  // 初次加载：若有 token 则自动获取用户信息
  useEffect(() => {
    if (!token) return
    apiFetch("/account/me")
      .then((r) => {
        if (!r.ok) { logout(); return null }
        return r.json()
      })
      .then((data) => { if (data) setUser(data) })
      .catch(() => logout())
  }, [token, logout])

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiFetch("/account/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.error || "登录失败")
    }
    const data = await res.json()
    storeToken(data.token)
    setToken(data.token)
    setUser(data.user)
  }, [])

  const register = useCallback(async (
    username: string, password: string,
    email = "", inviteCode = ""
  ) => {
    const res = await apiFetch("/account/register", {
      method: "POST",
      body: JSON.stringify({ username, password, email, invite_code: inviteCode }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.error || "注册失败")
    }
    const data = await res.json()
    storeToken(data.token)
    setToken(data.token)
    setUser(data.user)
  }, [])

  return (
    <AuthContext.Provider value={{ user, token, isAuthenticated: !!user, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider")
  return ctx
}

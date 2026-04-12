import { useEffect, useState, useCallback, useRef } from "react"

const API_BASE = "/api"

export function useApi<T>(url: string, options?: RequestInit) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = localStorage.getItem("_admin_token")
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...(options?.headers as Record<string, string>),
      }
      if (token) headers["Authorization"] = `Bearer ${token}`

      const res = await fetch(`${API_BASE}${url}`, { ...options, headers })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }, [url])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return { data, loading, error, refetch: fetchData }
}

export function useSSE(url: string, body: Record<string, unknown>) {
  const [content, setContent] = useState("")
  const [sources, setSources] = useState<{ title: string; url: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setContent("")
    setSources([])
    setError(null)

    try {
      const token = localStorage.getItem("_admin_token")
      const res = await fetch(`${API_BASE}${url}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          const raw = line.slice(6)
          if (raw === "[DONE]") return
          try {
            const event = JSON.parse(raw)
            if (event.type === "content") setContent((p) => p + (event.text || ""))
            else if (event.type === "sources") setSources(event.data ? JSON.parse(event.data) : [])
            else if (event.type === "error") setError(event.text || "Unknown error")
          } catch { /* skip malformed */ }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(err instanceof Error ? err.message : "Unknown error")
      }
    }
  }, [url, body])

  const abort = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  return { content, sources, error, send, abort }
}

/** 统一 API 请求工具 — 自动附加 Content-Type 和 Authorization header */
export function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem("_admin_token")
  const isBodyMethod = options.method === "POST" || options.method === "PUT" || options.method === "DELETE"
  const headers: Record<string, string> = {
    ...(isBodyMethod ? { "Content-Type": "application/json" } : {}),
    ...((options.headers as Record<string, string>) || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
  return fetch(`${API_BASE}${url}`, { ...options, headers })
}

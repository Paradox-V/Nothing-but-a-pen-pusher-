import { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Menu, X, Settings, Sun, Moon } from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "@/hooks/use-theme"

const navLinks = [
  { label: "新闻", tab: "news" },
  { label: "热榜", tab: "hotlist" },
  { label: "RSS", tab: "rss" },
  { label: "创作", tab: "creator" },
  { label: "问答", tab: "chat" },
  { label: "监控", tab: "monitor" },
]

interface NavbarProps {
  activeTab: string
  onTabChange: (tab: string) => void
}

export function Navbar({ activeTab, onTabChange }: NavbarProps) {
  const [scrolled, setScrolled] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const { theme, toggle } = useTheme()

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 20)
    window.addEventListener("scroll", handler, { passive: true })
    return () => window.removeEventListener("scroll", handler)
  }, [])

  const isVintage = theme === "vintage"

  return (
    <>
      <motion.header
        initial={{ y: -100 }}
        animate={{ y: 0 }}
        transition={{ type: "spring", stiffness: 100, damping: 20 }}
        className={cn(
          "fixed top-0 left-0 right-0 z-50 transition-all duration-500",
          scrolled
            ? "bg-background/80 backdrop-blur-2xl border-b border-border"
            : "bg-transparent"
        )}
      >
        <nav className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
          <button
            onClick={() => onTabChange("news")}
            className="text-[15px] font-semibold tracking-tight text-foreground/90 hover:text-foreground transition-colors"
          >
            信源汇总
          </button>

          {/* Desktop nav */}
          <div className="hidden md:flex items-center gap-1">
            {navLinks.map((link) => (
              <button
                key={link.tab}
                onClick={() => onTabChange(link.tab)}
                className={cn(
                  "relative px-3 py-1.5 text-[13px] font-medium rounded-full transition-colors",
                  activeTab === link.tab
                    ? "text-foreground"
                    : "text-foreground/50 hover:text-foreground/80"
                )}
              >
                {activeTab === link.tab && (
                  <motion.span
                    layoutId="nav-pill"
                    className={cn("absolute inset-0 rounded-full", isVintage ? "bg-accent" : "bg-muted")}
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  />
                )}
                <span className="relative z-10">{link.label}</span>
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={toggle}
              className={cn("p-2 rounded-full transition-all", "text-accent hover:bg-accent/10")}
              title={isVintage ? "切换深色模式" : "切换复古白模式"}
            >
              {isVintage ? <Moon size={16} /> : <Sun size={16} />}
            </button>
            <button
              onClick={() => {
                const token = prompt("设置管理密钥")
                if (token !== null) localStorage.setItem("_admin_token", token)
              }}
              className="p-2 rounded-full text-foreground/40 hover:text-foreground/70 hover:bg-muted transition-all"
            >
              <Settings size={16} />
            </button>
            <button
              onClick={() => setMobileOpen(!mobileOpen)}
              className="md:hidden p-2 rounded-full text-foreground/40 hover:text-foreground/70 hover:bg-muted transition-all"
            >
              {mobileOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
        </nav>
      </motion.header>

      {/* Mobile menu */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className={cn(
              "fixed top-14 left-0 right-0 z-40 backdrop-blur-2xl border-b border-border md:hidden",
              "bg-background/90"
            )}
          >
            <div className="px-6 py-3 flex flex-col gap-1">
              {navLinks.map((link) => (
                <button
                  key={link.tab}
                  onClick={() => {
                    onTabChange(link.tab)
                    setMobileOpen(false)
                  }}
                  className={cn(
                    "px-4 py-2.5 text-[14px] font-medium rounded-xl text-left transition-colors",
                    activeTab === link.tab
                      ? isVintage ? "text-white bg-accent" : "text-foreground bg-muted"
                      : "text-foreground/50 hover:text-foreground/80"
                  )}
                >
                  {link.label}
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}

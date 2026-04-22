import { useState, useEffect } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { ThemeProvider } from "@/hooks/use-theme"
import { AuthProvider } from "@/hooks/use-auth"
import { Navbar } from "@/components/layout/Navbar"
import { Footer } from "@/components/layout/Footer"
import { Hero } from "@/components/sections/Hero"
import { Features } from "@/components/sections/Features"
import { NewsPanel } from "@/components/sections/NewsPanel"
import { HotlistPanel } from "@/components/sections/HotlistPanel"
import { RssPanel } from "@/components/sections/RssPanel"
import { CreatorPanel } from "@/components/sections/CreatorPanel"
import { ChatPanel } from "@/components/sections/ChatPanel"
import { MonitorPanel } from "@/components/sections/MonitorPanel"
import { AccountPanel } from "@/components/sections/AccountPanel"
import { AdminPanel } from "@/components/sections/AdminPanel"

interface AppStatus {
  news_count?: number
  rss_feed_count?: number
  ai_available?: boolean
  hotlist_last_crawl?: string
}

const panels: Record<string, React.FC> = {
  news: NewsPanel,
  hotlist: HotlistPanel,
  rss: RssPanel,
  creator: CreatorPanel,
  chat: ChatPanel,
  monitor: MonitorPanel,
  account: AccountPanel,
  admin: AdminPanel,
}

function AppInner() {
  const [activeTab, setActiveTab] = useState("landing")
  const [status, setStatus] = useState<AppStatus>({})

  useEffect(() => {
    fetch("/api/status")
      .then((r) => r.json())
      .then((d) => setStatus(d))
      .catch((err) => console.error("Status check failed:", err))
  }, [])

  const handleTabChange = (tab: string) => {
    setActiveTab(tab)
    window.scrollTo({ top: 0, behavior: "smooth" })
  }

  const handleExplore = () => {
    setActiveTab("news")
    window.scrollTo({ top: 0, behavior: "smooth" })
  }

  const isLanding = activeTab === "landing"
  const Panel = panels[activeTab]

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar
        activeTab={isLanding ? "" : activeTab}
        onTabChange={handleTabChange}
      />

      <main className="pt-14">
        <AnimatePresence mode="wait">
          {isLanding ? (
            <motion.div
              key="landing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.4 }}
            >
              <Hero
                stats={{
                  newsCount: status.news_count,
                  rssCount: status.rss_feed_count,
                  aiReady: status.ai_available,
                }}
                onExplore={handleExplore}
              />
              <Features />
            </motion.div>
          ) : (
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.3, ease: [0.25, 0.4, 0.25, 1] as [number, number, number, number] }}
            >
              {Panel && <Panel />}
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {isLanding && <Footer />}
    </div>
  )
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AppInner />
      </AuthProvider>
    </ThemeProvider>
  )
}

export default App

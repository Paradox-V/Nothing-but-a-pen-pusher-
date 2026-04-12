import { motion } from "framer-motion"
import { ArrowRight, Sparkles } from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "@/hooks/use-theme"

interface HeroProps {
  stats: {
    newsCount?: number
    rssCount?: number
    aiReady?: boolean
  }
  onExplore: () => void
}

export function Hero({ stats, onExplore }: HeroProps) {
  const { theme } = useTheme()
  const v = theme === "vintage"

  return (
    <section className="relative min-h-[90vh] flex flex-col items-center justify-center px-6 overflow-hidden">
      {/* Radial gradient background */}
      {v ? (
        <>
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(79,121,66,0.10)_0%,_transparent_60%)]" />
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-[radial-gradient(circle,_rgba(79,121,66,0.06)_0%,_transparent_50%)]" />
        </>
      ) : (
        <>
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(10,132,255,0.08)_0%,_transparent_70%)]" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-[radial-gradient(circle,_rgba(94,92,230,0.06)_0%,_transparent_60%)]" />
        </>
      )}

      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: [0.25, 0.4, 0.25, 1] as [number, number, number, number] }}
        className="relative z-10 text-center max-w-4xl"
      >
        {/* Eyebrow */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.2, duration: 0.5 }}
          className={cn(
            "inline-flex items-center gap-2 px-4 py-1.5 rounded-full border text-[12px] font-medium tracking-wide uppercase mb-8",
            v
              ? "bg-[#4F7942]/10 border-[#4F7942]/20 text-[#4F7942]"
              : "bg-muted border-border text-muted-foreground"
          )}
        >
          <Sparkles size={13} className="text-accent" />
          AI 驱动的智能信息中枢
        </motion.div>

        {/* Main headline */}
        <h1 className="text-[clamp(40px,8vw,80px)] font-bold tracking-tighter leading-[0.95] text-foreground">
          信息，
          <br />
          <span className={v
            ? "bg-gradient-to-r from-[#2C2E31] via-[#4F7942] to-[#3B5E32] bg-clip-text text-transparent"
            : "bg-gradient-to-r from-white via-white/90 to-white/60 bg-clip-text text-transparent"
          }>
            尽在掌握。
          </span>
        </h1>

        {/* Subtitle */}
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4, duration: 0.6 }}
          className="mt-6 text-[17px] leading-relaxed text-muted-foreground max-w-xl mx-auto"
        >
          聚合新闻热榜、RSS 订阅、AI 选题创作与智能问答，
          <br className="hidden sm:block" />
          用向量语义检索重新定义你的信息工作流。
        </motion.p>

        {/* Stats */}
        {stats && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.6, duration: 0.6 }}
            className="mt-10 flex items-center justify-center gap-8 text-[13px] text-muted-foreground"
          >
            {stats.newsCount != null && (
              <span>
                <span className={v ? "text-[#4F7942] font-medium tabular-nums" : "text-foreground/70 font-medium tabular-nums"}>
                  {stats.newsCount.toLocaleString()}
                </span>{" "}
                篇新闻
              </span>
            )}
            {stats.rssCount != null && (
              <span>
                <span className={v ? "text-[#4F7942] font-medium tabular-nums" : "text-foreground/70 font-medium tabular-nums"}>
                  {stats.rssCount}
                </span>{" "}
                个订阅源
              </span>
            )}
            {stats.aiReady && (
              <span className="flex items-center gap-1.5">
                <span className={v
                  ? "w-2 h-2 rounded-full bg-[#4F7942] animate-pulse"
                  : "w-1.5 h-1.5 rounded-full bg-[#30d158] animate-pulse"
                } />
                AI 就绪
              </span>
            )}
          </motion.div>
        )}

        {/* CTA */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.8, duration: 0.6 }}
          className="mt-10"
        >
          <button
            onClick={onExplore}
            className={v
              ? "group inline-flex items-center gap-2 px-8 py-3.5 bg-[#4F7942] text-white text-[15px] font-semibold rounded-full hover:bg-[#3B5E32] transition-all hover:gap-3 shadow-lg shadow-[#4F7942]/20"
              : "group inline-flex items-center gap-2 px-7 py-3 bg-white text-black text-[15px] font-semibold rounded-full hover:bg-white/90 transition-all hover:gap-3"
            }
          >
            开始探索
            <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" />
          </button>
        </motion.div>
      </motion.div>
    </section>
  )
}


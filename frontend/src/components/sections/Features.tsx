import { motion } from "framer-motion"
import {
  Newspaper, TrendingUp, Rss, PenTool, MessageCircle, Search, Zap, Layers,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useTheme } from "@/hooks/use-theme"

const featureDefs = [
  { icon: Newspaper, title: "新闻聚合", description: "多源采集、语义分类、向量检索，让每一条新闻精准触达", span: "col-span-2 md:col-span-1 lg:col-span-2" },
  { icon: TrendingUp, title: "热榜追踪", description: "全平台热点实时汇聚，跨平台热度对比分析", span: "col-span-1" },
  { icon: Rss, title: "RSS 订阅", description: "智能 Feed 发现，自定义 CSS 选择器，一站式管理", span: "col-span-1" },
  { icon: Search, title: "语义检索", description: "基于向量嵌入的深度语义搜索，超越关键词匹配的局限", span: "col-span-1" },
  { icon: PenTool, title: "AI 选题创作", description: "热点发现 → 框架生成 → 智能写作，AI 全链路辅助创作", span: "col-span-2 md:col-span-1 lg:col-span-2" },
  { icon: MessageCircle, title: "智能问答", description: "基于 RAG 的对话式问答，精准引用新闻源", span: "col-span-1" },
]

const gradientsDark = [
  "from-[#0a84ff]/20 to-transparent",
  "from-[#ff9f0a]/20 to-transparent",
  "from-[#30d158]/20 to-transparent",
  "from-[#5e5ce6]/20 to-transparent",
  "from-[#ff375f]/20 to-transparent",
  "from-[#bf5af2]/20 to-transparent",
]

const gradientsVintage = [
  "from-accent/20 to-transparent",
  "from-accent/18 to-transparent",
  "from-accent/15 to-transparent",
  "from-accent/15 to-transparent",
  "from-accent/22 to-transparent",
  "from-accent/18 to-transparent",
]

const techFeatures = [
  { icon: Zap, label: "向量引擎" },
  { icon: Layers, label: "BGE 嵌入模型" },
]

const containerVariants = { hidden: {}, visible: { transition: { staggerChildren: 0.08 } } }
const itemVariants = {
  hidden: { opacity: 0, y: 20, scale: 0.98 },
  visible: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.5, ease: [0.25, 0.4, 0.25, 1] as [number, number, number, number] } },
}

export function Features() {
  const { theme } = useTheme()
  const v = theme === "vintage"
  const gradients = v ? gradientsVintage : gradientsDark

  return (
    <section className="py-24 lg:py-32 px-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
          className="text-center mb-16"
        >
          <h2 className="text-[clamp(28px,5vw,48px)] font-bold tracking-tighter text-foreground">
            强大功能，一站整合。
          </h2>
          <p className="mt-4 text-[17px] text-foreground/40 max-w-lg mx-auto">
            六大核心模块，覆盖信息采集、分析、创作的完整链路
          </p>
          {v && (
            <motion.div
              initial={{ scaleX: 0 }}
              whileInView={{ scaleX: 1 }}
              viewport={{ once: true }}
              transition={{ delay: 0.4, duration: 0.6 }}
              className="mt-6 mx-auto w-24 h-0.5 bg-accent rounded-full origin-center"
            />
          )}
        </motion.div>

        {/* Bento Grid */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-50px" }}
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3"
        >
          {featureDefs.map((feature, i) => (
            <motion.div
              key={feature.title}
              variants={itemVariants}
              className={cn(
                "group relative overflow-hidden rounded-2xl lg:rounded-3xl bg-card border p-6 lg:p-8 transition-all duration-500",
                feature.span,
                "border-accent/8 hover:border-accent/25"
              )}
            >
              <div className={cn("absolute inset-0 bg-gradient-to-br opacity-0 group-hover:opacity-100 transition-opacity duration-700", gradients[i])} />

              <div className="relative z-10">
                <div className={cn(
                  "w-10 h-10 rounded-xl flex items-center justify-center mb-4",
                  "bg-accent/12"
                )}>
                  <feature.icon size={20} className={"text-accent"} />
                </div>
                <h3 className="text-[17px] font-semibold tracking-tight text-foreground mb-2">
                  {feature.title}
                </h3>
                <p className="text-[14px] leading-relaxed text-foreground/35">
                  {feature.description}
                </p>
              </div>
            </motion.div>
          ))}
        </motion.div>

        {/* Tech strip */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ delay: 0.3, duration: 0.5 }}
          className="mt-8 flex items-center justify-center gap-6 text-[12px] text-foreground/25 uppercase tracking-wider"
        >
          {techFeatures.map((t) => (
            <span key={t.label} className={cn("flex items-center gap-2", v && "text-accent/40")}>
              <t.icon size={13} />
              {t.label}
            </span>
          ))}
        </motion.div>
      </div>
    </section>
  )
}

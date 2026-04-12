import { useState, useRef, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

interface DropdownOption {
  value: string
  label: string
  disabled?: boolean
}

interface DropdownProps {
  value: string
  onChange: (value: string) => void
  options: DropdownOption[]
  placeholder?: string
  className?: string
  minWidth?: number
}

export function Dropdown({ value, onChange, options, placeholder = "请选择", className, minWidth = 120 }: DropdownProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const selected = options.find((o) => o.value === value)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  return (
    <div ref={ref} className="relative" style={{ minWidth }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "w-full flex items-center justify-between gap-2 px-3 py-2.5 bg-muted border border-border rounded-xl text-[13px] focus:outline-none cursor-pointer transition-colors hover:border-accent/30",
          !selected && "text-muted-foreground",
          className
        )}
      >
        <span className="truncate">{selected ? selected.label : placeholder}</span>
        <ChevronDown size={14} className={cn("shrink-0 text-muted-foreground transition-transform duration-200", open && "rotate-180")} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="absolute top-full left-0 right-0 mt-1.5 z-50 py-1 bg-card border border-border rounded-xl shadow-xl overflow-hidden"
          >
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={opt.disabled}
                onClick={() => {
                  if (!opt.disabled) { onChange(opt.value); setOpen(false) }
                }}
                className={cn(
                  "w-full text-left px-3 py-2 text-[13px] transition-colors",
                  opt.disabled
                    ? "text-muted-foreground/40 cursor-default"
                    : opt.value === value
                      ? "bg-accent/10 text-accent font-medium"
                      : "text-foreground/70 hover:bg-muted hover:text-foreground"
                )}
              >
                {opt.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

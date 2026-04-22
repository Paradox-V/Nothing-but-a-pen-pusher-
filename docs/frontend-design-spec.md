# Pen Pusher 前端组件设计规范

> 最后更新：2026-04-21
> 适用范围：`frontend/src/` 下所有组件

---

## 1. 设计系统基础

### 1.1 技术栈

| 层级 | 技术 |
|------|------|
| 框架 | React 19 + TypeScript |
| 构建 | Vite 8 |
| 样式 | Tailwind CSS 4 |
| UI 基础 | shadcn/ui (base-nova style) + @base-ui/react |
| 动画 | Framer Motion 12 |
| 图标 | Lucide React |
| 类合并 | `cn()` = `clsx` + `tailwind-merge` |

### 1.2 主题系统

双主题通过 CSS 自定义属性实现，`useTheme()` 返回 `"midnight"` 或 `"vintage"`。

```tsx
// 组件中获取主题
import { useTheme } from "@/hooks/use-theme"
const { theme } = useTheme()
const v = theme === "vintage"
```

**禁止硬编码颜色值**（如 `bg-[#4F7942]`），应使用语义 token（如 `bg-accent`）。Vintage 差异通过 `cn(v ? ... : ...)` 处理。

| Token | Midnight | Vintage |
|-------|----------|---------|
| `bg-background` | `#000000` | `#E8E9E4` |
| `bg-card` | `#111113` | `#DDDED8` |
| `bg-muted` | `#1c1c1e` | `#D2D3CD` |
| `text-foreground` | `#fafafa` | `#2C2E31` |
| `text-muted-foreground` | `#8e8e93` | `#6B6D70` |
| `bg-accent` | `#0a84ff` | `#4F7942` |
| `border` | `rgba(255,255,255,0.08)` | `rgba(44,46,49,0.10)` |

---

## 2. 组件使用规范

### 2.1 核心规则：使用项目组件，不使用原生 HTML

| 需求 | 必须使用 | 禁止使用 |
|------|---------|---------|
| 下拉选择 | `<Dropdown>` (`shared/Dropdown`) | `<select>` |
| 文本输入 | `<Input>` (`ui/input`) | `<input>` (除非 Input 不满足需求) |
| 按钮 | `<Button>` (`ui/button`) | `<button>` (除非 Button 不满足需求) |
| 弹窗 | `<Dialog>` (`ui/dialog`) | 自写 overlay |
| 徽章 | `<Badge>` (`ui/badge`) | 自写 span |
| 卡片 | `<Card>` (`ui/card`) | 自写 div |

**例外**：如果 UI 组件的样式约束导致无法实现设计需求，可以在组件内用 `className` 覆盖，而不是回退到原生元素。

### 2.2 Dropdown 组件

```
路径：@/components/shared/Dropdown
```

```tsx
import { Dropdown } from "@/components/shared/Dropdown"

<Dropdown
  value={currentValue}
  onChange={setValue}
  options={[
    { value: "a", label: "选项 A" },
    { value: "b", label: "选项 B", disabled: true },
  ]}
  placeholder="请选择"    // 可选，默认 "请选择"
  minWidth={120}          // 可选，默认 120
  className="text-sm"     // 可选覆盖
/>
```

**视觉规格**：
- 触发器：`bg-muted border-border rounded-xl px-3 py-2.5 text-[13px]`
- 下拉箭头：Lucide `ChevronDown` 14px，展开时旋转 180°
- 面板：`bg-card border-border rounded-xl shadow-xl`，带 framer-motion 弹出动画
- 选中项：`bg-accent/10 text-accent font-medium`
- 悬停项：`bg-muted text-foreground`
- 禁用项：`text-muted-foreground/40`

---

## 3. 布局规范

### 3.1 页面容器

所有面板页面使用统一的容器结构：

```tsx
<div className="max-w-7xl mx-auto px-6 py-8">
```

| 面板类型 | max-width |
|----------|-----------|
| 列表类（新闻、热榜、RSS、聊天） | `max-w-7xl` |
| 创作工具 | `max-w-5xl` |
| 配置/管理 | `max-w-4xl` |

### 3.2 卡片网格

```tsx
// 双列卡片
<div className="grid grid-cols-1 md:grid-cols-2 gap-3">
```

### 3.3 间距

| 场景 | 值 |
|------|-----|
| 面板标题与内容 | `mb-6` |
| 卡片之间 | `gap-3` |
| 表单项之间 | `space-y-3` |
| 行内元素间距 | `gap-2` 或 `gap-3` |

---

## 4. 排版规范

### 4.1 字号

使用 Tailwind 标准尺寸，避免任意像素值：

| 用途 | 类名 | 近似值 |
|------|------|--------|
| 面板主标题 | `text-lg font-semibold` | 18px |
| 卡片标题 | `text-sm font-medium` | 14px |
| 正文/搜索输入 | `text-sm` | 14px |
| 标签/辅助文字 | `text-xs` | 12px |
| 微型标注 | `text-[10px]` | 10px |
| 下拉选项 | `text-[13px]` | 13px |

### 4.2 字重

| 用途 | 类名 |
|------|------|
| 面板标题 | `font-semibold` |
| 按钮/卡片标题 | `font-medium` |
| 正文 | 默认 (400) |
| 状态徽章 | `font-bold` |

### 4.3 文字颜色层级

```tsx
// 主文字
"text-foreground"

// 次要文字（描述、时间戳）
"text-foreground/50"        // midnight
"text-[#2C2E31]/50"         // vintage（需要 v 判断时）

// 占位符
"placeholder:text-foreground/25"

// 禁用/最弱层级
"text-foreground/30"
```

---

## 5. 交互组件规范

### 5.1 按钮

**主按钮（强调操作）**：
```tsx
className={cn(
  "px-4 py-2 rounded-lg text-sm font-medium transition-all",
  v ? "bg-[#4F7942] text-white hover:bg-[#3B5E32]"
    : "bg-accent text-accent-foreground hover:bg-accent/90"
)}
```

**次要按钮**：
```tsx
className="px-4 py-2 rounded-lg text-sm font-medium bg-muted text-foreground/60 hover:text-foreground/80 border border-border"
```

**幽灵按钮（取消等）**：
```tsx
className="px-4 py-2 rounded-lg text-sm text-foreground/40 hover:text-foreground/60"
```

**图标按钮**：
```tsx
className={cn(
  "p-2.5 rounded-xl border transition-all",
  v ? "bg-[#3B5E32] border-[#3B5E32] text-white hover:bg-[#324F2B]"
    : "bg-muted border-border text-muted-foreground hover:text-foreground"
)}
```

### 5.2 输入框

**搜索输入**：
```tsx
className="w-full pl-11 pr-4 py-2.5 bg-muted border border-border rounded-xl
  text-sm text-foreground placeholder:text-foreground/25
  focus:outline-none focus:border-accent/30 transition-colors"
```

**表单输入**：
```tsx
className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground
  focus:outline-none focus:border-accent/30"
```

### 5.3 卡片

**内容卡片**：
```tsx
className={cn(
  "rounded-2xl bg-card border border-border p-5 hover:border-foreground/10 transition-all",
  v && "hover:border-[#4F7942]/20"
)}
```

**表单/内联卡片**：
```tsx
className={cn(
  "rounded-2xl border p-4 space-y-3",
  v ? "bg-[#E8E9E4] border-[#4F7942]/20" : "bg-card border-border"
)}
```

### 5.4 状态徽章

```tsx
// 通用状态
className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-{color}/10 text-{color}"

// 分类标签
className="px-2 py-0.5 rounded-md bg-muted text-[11px] text-muted-foreground font-medium"

// 高亮标签
className="px-2 py-0.5 rounded-md bg-accent/10 text-[11px] text-accent font-medium"
```

**状态颜色标准**（禁止硬编码色值）：

| 状态 | 类名 |
|------|------|
| 成功/在线 | `bg-green-500/10 text-green-500` |
| 失败/错误 | `bg-red-500/10 text-red-500` |
| 强调 | `bg-accent/10 text-accent` |
| 中性/暂停 | `bg-foreground/10 text-foreground/40` |
| 警告 | `bg-[#ff9f0a]/10 text-[#ff9f0a]` |

---

## 6. 圆角规范

| 组件 | 圆角 | 类名 |
|------|------|------|
| 面板内容卡片 | 16px | `rounded-2xl` |
| 输入框（搜索） | 12px | `rounded-xl` |
| 输入框（表单） | 8px | `rounded-lg` |
| 下拉菜单 | 12px | `rounded-xl` |
| 按钮 | 8px | `rounded-lg` |
| 图标按钮 | 12px | `rounded-xl` |
| 状态徽章 | 4px | `rounded` |
| 标签徽章 | 6px | `rounded-md` |

---

## 7. 动画规范

### 7.1 使用 Framer Motion

```tsx
import { motion } from "framer-motion"

// 淡入上滑（列表项、表单展开）
<motion.div
  initial={{ opacity: 0, y: -10 }}
  animate={{ opacity: 1, y: 0 }}
>

// 下拉菜单弹出
<motion.div
  initial={{ opacity: 0, y: -4, scale: 0.98 }}
  animate={{ opacity: 1, y: 0, scale: 1 }}
  exit={{ opacity: 0, y: -4, scale: 0.98 }}
  transition={{ duration: 0.15 }}
>
```

### 7.2 CSS Transition

```tsx
// 所有可交互元素加 transition-all
"transition-all"
"transition-colors"  // 仅颜色变化时
```

---

## 8. Toast 通知规范

```tsx
// 固定右上角
className="fixed top-4 right-4 z-[100] px-4 py-2.5 rounded-xl
  bg-card border border-border text-[13px] text-foreground shadow-lg"
```

使用 `AnimatePresence` + `motion.div` 实现进出动画，3 秒自动消失。

---

## 9. 弹窗/遮罩规范

```tsx
// 遮罩层
className="fixed inset-0 z-50 bg-foreground/60 backdrop-blur-xl"

// 弹窗内容
className="max-w-lg bg-card border border-border rounded-2xl p-6 max-h-[80vh] overflow-auto"
```

优先使用 `<Dialog>` UI 组件。

---

## 10. 禁止事项

1. **禁止使用原生 `<select>`** — 必须用 `<Dropdown>`
2. **禁止硬编码颜色** — 用语义 token（`bg-accent`、`text-foreground`），vintage 差异走 `cn(v ? ... : ...)`
3. **禁止重复造轮子** — 如果 `ui/` 或 `shared/` 已有组件，优先复用
4. **禁止不带 `focus` 样式的输入** — 至少加 `focus:border-accent/30`
5. **禁止不一致的 vintage 传参** — 统一使用 `useTheme()` hook，不要通过 props 传 `v`

---

## 11. 文件组织

```
src/components/
  ui/              → shadcn/ui 基础组件（button, card, input, dialog, badge...）
  shared/          → 项目级共享组件（Dropdown, Empty, Loading, AnimateIn）
  layout/          → 布局组件（Navbar, Footer）
  sections/        → 面板/页面组件（按功能分目录）
    monitor/       → 监控模块子组件
    ...
```

**新增组件放置规则**：
- 通用可复用 → `shared/`
- 符合 shadcn 规范 → `ui/`（通过 `npx shadcn add` 添加）
- 面板专属 → `sections/{panel}/`

---

## 12. 检查清单（PR 前自查）

- [ ] 无原生 `<select>` 元素
- [ ] 颜色使用语义 token，非硬编码值
- [ ] 输入框有 focus 样式
- [ ] 卡片有 hover 过渡
- [ ] Vintage 主题下视觉正常
- [ ] 新增共享组件已放入正确目录
- [ ] 圆角符合本规范第 6 节
- [ ] 字号使用 Tailwind 标准尺寸

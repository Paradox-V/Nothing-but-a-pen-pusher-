"""监控任务执行服务 —— 报告生成 + 推送 + 防重入"""

import json
import logging
import threading
from datetime import datetime
from typing import Generator

from modules.monitor.db import MonitorDB
from modules.monitor.push import send_push
from utils.scheduler_client import scheduler_post

logger = logging.getLogger(__name__)

# ── 模块级防重入锁（scheduler 和 routes 共享） ──
_running_lock = threading.Lock()
_running_tasks: set[str] = set()
_monitor_service_instance = None
_singleton_lock = threading.Lock()


def get_monitor_service() -> "MonitorService":
    """模块级单例，确保 scheduler 和 routes 共享同一实例和锁。"""
    global _monitor_service_instance
    if _monitor_service_instance is None:
        with _singleton_lock:
            if _monitor_service_instance is None:
                _monitor_service_instance = MonitorService()
    return _monitor_service_instance


REPORT_PROMPT = """你是"信源汇总"平台的智能监控助手。根据以下检索到的信息，生成一份简洁的监控报告。

报告结构：
## 今日概览
（一句话总结关键发现）

## 重点事件
（列出 2-3 个最重要的事件，每个事件标注来源）

## 趋势研判
（简要分析趋势方向）

规则：
- 只基于检索到的资料，不要编造
- 引用来源标注 [来源名]
- 控制在 500 字以内
- 使用中文

检索结果：
{context}"""


class MonitorService:
    """监控任务执行服务。"""

    def __init__(self):
        self.db = MonitorDB()
        # 注意：防重入锁是模块级的（_running_lock / _running_tasks），不在实例上。

    # ── 任务 CRUD（代理到 DB，脱敏在 DB 层处理） ──

    def create_task(self, name: str, keywords: list, filters: dict | None,
                    schedule: str, push_config: list,
                    owner_id: str | None = None) -> dict:
        import uuid
        task_id = str(uuid.uuid4())
        return self.db.create_task(task_id, name, keywords, filters, schedule,
                                   push_config, owner_id=owner_id)

    def get_tasks(self) -> list[dict]:
        return self.db.get_tasks()

    def get_task(self, task_id: str) -> dict | None:
        return self.db.get_task(task_id)

    def update_task(self, task_id: str, **kwargs) -> dict | None:
        return self.db.update_task(task_id, **kwargs)

    def delete_task(self, task_id: str) -> bool:
        ok = self.db.delete_task(task_id)
        if ok:
            # 清理 WCF 绑定关联
            try:
                from modules.wcf.db import WCFDB
                WCFDB().delete_task_bindings(task_id)
            except Exception:
                pass
        return ok

    def is_task_running(self, task_id: str) -> bool:
        """检查任务是否正在执行。"""
        with _running_lock:
            return task_id in _running_tasks

    def get_push_logs(self, task_id: str, limit: int = 20) -> list[dict]:
        return self.db.get_push_logs(task_id, limit)

    # ── 到期任务判断 ──

    def get_due_tasks(self) -> list[dict]:
        """返回当前时间应该执行的任务。"""
        from utils.config import load_config
        config = load_config()
        monitor_cfg = config.get("monitor", {})
        schedules = monitor_cfg.get("schedules", {
            "daily_morning": "08:00",
            "daily_evening": "20:00",
        })

        tasks = self.db.get_active_tasks()
        due = []
        for task in tasks:
            if self._is_task_due(task, schedules):
                due.append(task)
        return due

    @staticmethod
    def _is_task_due(task: dict, schedules: dict) -> bool:
        """根据配置的时间窗口判断任务是否到期。"""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # 防御性处理 None 和空字符串
        last_run = task.get("last_run_at") or ""
        if isinstance(last_run, str) and last_run.startswith(today):
            return False

        schedule = task.get("schedule", "daily_morning")
        target_time = schedules.get(schedule, "08:00")
        hour, minute = map(int, target_time.split(":"))

        # 单边时间窗：目标时间之后 1 小时内触发
        target_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < target_dt:
            return False
        return (now - target_dt).total_seconds() < 3600

    # ── 任务执行 ──

    def build_report(self, task_id: str) -> str:
        """搜索 + LLM 生成报告，不推送。

        Returns:
            生成的报告文本
        Raises:
            ValueError: 任务不存在
        """
        task = self.db.get_task_raw(task_id)
        if not task:
            raise ValueError(f"task not found: {task_id}")

        keywords = json.loads(task["keywords"])
        all_results = []

        # 1) 合并关键词为一次宽泛搜索
        merged_query = " ".join(keywords)
        merged = scheduler_post(
            "/chat_search",
            json_data={"query": merged_query, "top_k": 10},
            timeout=15,
        )
        if merged and isinstance(merged, list):
            all_results.extend(merged)

        # 2) 并行搜索各个关键词，补充长尾结果
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from functools import partial
        with ThreadPoolExecutor(max_workers=min(len(keywords), 4)) as pool:
            futures = {
                pool.submit(
                    partial(scheduler_post, "/chat_search",
                            json_data={"query": kw, "top_k": 3},
                            timeout=15),
                ): kw for kw in keywords
            }
            for future in as_completed(futures):
                kw = futures[future]
                try:
                    results = future.result()
                    if results and isinstance(results, list):
                        all_results.extend(results)
                except Exception as exc:
                    logger.warning("并行搜索关键词 '%s' 失败: %s", kw, exc)

        # 按标题去重
        seen = set()
        deduped = []
        for r in all_results:
            key = r.get("title", "") or r.get("content", "")[:50]
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        return self._generate_report(task["name"], keywords, deduped)

    def deliver_report(self, report: str, push_config: list,
                       task_id: str = "") -> list[dict]:
        """推送到指定渠道列表，记录推送日志。

        Args:
            report: 报告内容
            push_config: 推送渠道配置列表
            task_id: 任务 ID（用于日志记录）
        Returns:
            推送结果列表
        """
        push_results = []
        for channel in push_config:
            ok, err = send_push(report, channel)
            push_results.append({
                "type": channel.get("type", ""),
                "success": ok,
                "error": err,
            })

        if task_id:
            if not push_results:
                self.db.log_push(
                    task_id, status="failed",
                    error="no push targets (empty push_config after expansion)",
                )
            else:
                all_ok = all(r["success"] for r in push_results)
                self.db.log_push(
                    task_id,
                    status="success" if all_ok else "partial",
                    report_summary=report[:500],
                )
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.db.update_task(task_id, last_run_at=now_str)

        return push_results

    def run_task(self, task_id: str, override_push_config: list | None = None) -> dict:
        """执行监控任务。

        Args:
            task_id: 任务 ID
            override_push_config: 覆盖推送渠道（微信指令回复时使用）。
                为 None 时使用任务原配置。
        """
        with _running_lock:
            if task_id in _running_tasks:
                return {"status": "skipped", "reason": "already running"}
            _running_tasks.add(task_id)

        try:
            report = self.build_report(task_id)

            push_config = override_push_config
            if push_config is None:
                task = self.db.get_task_raw(task_id)
                push_config = json.loads(task["push_config"])

            # 展开 WCF 渠道：将 [{ type: "wcf" }] 替换为绑定的联系人列表
            push_config = self._expand_wcf_push_config(push_config, task_id)

            push_results = self.deliver_report(report, push_config, task_id=task_id)

            return {"status": "success", "report_length": len(report)}

        except ValueError as e:
            return {"status": "error", "reason": str(e)}
        except Exception as e:
            logger.error("Monitor task %s failed: %s", task_id, e)
            try:
                self.db.log_push(task_id, status="failed", error=str(e))
            except Exception:
                pass
            return {"status": "error", "reason": str(e)}

        finally:
            with _running_lock:
                _running_tasks.discard(task_id)

    def _expand_wcf_push_config(self, push_config: list, task_id: str) -> list:
        """展开 WCF 渠道：若 push_config 中有 { type: "wcf" } 且缺少 account_id/to_user_id，
        则查询 wcf_binding_tasks 获取绑定的联系人，展开为具体的推送目标。

        旧格式 { type: "wcf", url: "...", secret: "acc::user" } 不受影响。
        新格式 { type: "wcf", account_id: "...", to_user_id: "..." } 不受影响。
        简写格式 { type: "wcf" } 展开为所有绑定的已启用联系人。
        """
        expanded = []
        has_wcf_shorthand = False

        for ch in push_config:
            if ch.get("type") != "wcf":
                expanded.append(ch)
                continue

            # 已有 account_id + to_user_id 或旧格式 secret → 直接使用
            if ch.get("account_id") and ch.get("to_user_id"):
                expanded.append(ch)
                continue
            if ch.get("secret") or ch.get("url"):
                expanded.append(ch)
                continue

            # 简写格式：查询绑定的联系人
            has_wcf_shorthand = True
            try:
                from modules.wcf.db import WCFDB
                wcf_db = WCFDB()
                bindings = wcf_db.get_bindings_for_task(task_id)
                for b in bindings:
                    if b.get("enabled"):
                        expanded.append({
                            "type": "wcf",
                            "account_id": b["account_id"],
                            "to_user_id": b["user_id"],
                            "context_token": b.get("context_token", ""),
                        })
            except Exception as e:
                logger.error("Failed to expand WCF push config: %s", e)
            continue

        if has_wcf_shorthand and not any(
            c.get("type") == "wcf" for c in expanded
        ):
            logger.warning("Task %s has WCF push but no enabled bindings", task_id)

        return expanded

    def _generate_report(self, task_name: str, keywords: list,
                         results: list[dict]) -> str:
        """用 LLM 生成结构化监控报告。"""
        if not results:
            return f"## {task_name} 监控报告\n\n今日未检索到与 {', '.join(keywords)} 相关的新内容。"

        # 格式化上下文
        context_parts = []
        for i, r in enumerate(results[:15], 1):
            source = r.get("source_name", r.get("platform_name", "未知来源"))
            title = r.get("title", "")
            content = r.get("content", "")
            if content and content != title:
                context_parts.append(f"[{i}] [{source}] {title}\n{content[:200]}")
            else:
                context_parts.append(f"[{i}] [{source}] {title}")

        context = "\n\n".join(context_parts)

        # 调用 LLM
        try:
            from ai.config import get_ai_config
            ai_cfg = get_ai_config()
            if not ai_cfg.get("API_KEY"):
                raise RuntimeError("AI API Key 未配置，跳过 LLM")
            from ai.langchain_config import get_chat_model
            llm = get_chat_model(temperature=0.5, max_tokens=1000)
            prompt = REPORT_PROMPT.format(context=context)
            response = llm.invoke(prompt)
            return f"## {task_name} 监控报告\n\n{response.content}"
        except Exception as e:
            logger.error("Report generation failed: %s", e)
            # 回退：简单罗列
            lines = [f"## {task_name} 监控报告\n"]
            for r in results[:10]:
                source = r.get("source_name", r.get("platform_name", ""))
                title = r.get("title", "")
                lines.append(f"- [{source}] {title}")
            return "\n".join(lines)

    def test_push(self, push_config: list) -> dict:
        """发送测试消息到指定渠道。"""
        test_content = (
            "## 信源汇总 - 推送测试\n\n"
            f"测试时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "如果你看到了这条消息，说明推送渠道配置正确。"
        )
        results = []
        for channel in push_config:
            ok, err = send_push(test_content, channel)
            results.append({"type": channel.get("type", ""), "success": ok, "error": err})
        return {"results": results}

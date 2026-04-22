"""WCF 事件消费 + 指令处理服务"""

import json
import logging
import time

from modules.wcf import client
from modules.wcf.db import WCFDB

logger = logging.getLogger(__name__)

_db = WCFDB()

# 微信单条消息最大长度（字符）
_WX_MAX_MSG_LEN = 1800


def consume_events():
    """从 wcfLink 拉取新事件并处理。

    游标推进语义：
    - 分类完成（outbound、非文本、非指令文本）→ 推进游标
    - 指令处理成功 → 推进游标
    - 处理失败（临时异常）→ 不推进，下次重试
    """
    from utils.config import load_config
    config = load_config()
    wcf_cfg = config.get("wcf", {})
    batch_size = wcf_cfg.get("event_batch_size", 100)

    cursor = _db.get_cursor()
    events = client.list_events(after_id=cursor, limit=batch_size)

    if not events:
        return

    # 按 id 升序处理
    for event in sorted(events, key=lambda e: e.get("id", 0)):
        try:
            result = _process_event(event)
            # 分类完成或指令处理成功 → 推进
            if result:
                _db.set_cursor(event["id"])
            # result=False 表示处理失败，不推进游标，下次重试
        except Exception as e:
            logger.error("WCF event %s process error: %s", event.get("id"), e)
            # 异常不推进游标


def _process_event(event: dict) -> bool:
    """处理单条事件。

    Returns:
        True: 分类完成或指令处理成功，可推进游标
        False: 处理失败，不应推进游标
    """
    event_id = event.get("id", 0)
    direction = event.get("direction", "")
    account_id = event.get("account_id", "")
    from_user_id = event.get("from_user_id", "")
    context_token = event.get("context_token", "")
    body_text = event.get("body_text", "")

    # outbound 事件：分类完成，推进游标
    if direction != "inbound":
        return True

    # 非文本消息：upsert 联系人，分类完成
    event_type = event.get("event_type", "")
    if event_type != "text":
        _db.upsert_binding(
            account_id, from_user_id,
            context_token=context_token,
            last_message=f"[{event_type}]",
        )
        return True

    # 文本消息：upsert 联系人 + 处理指令
    _db.upsert_binding(
        account_id, from_user_id,
        context_token=context_token,
        last_message=body_text,
    )
    try:
        handle_command(account_id, from_user_id, body_text)
        return True
    except Exception as e:
        logger.error("WCF command handling failed for event %s: %s", event_id, e)
        return False


def handle_command(account_id: str, user_id: str, text: str):
    """匹配并执行微信指令；非指令消息路由到 Agent。

    指令范围：帮助、监控列表、报告、报告 <任务名>
    未匹配指令 → 若 agent_enabled 则走 Agent，否则忽略
    """
    text = text.strip()
    if not text:
        return

    from utils.config import load_config
    config = load_config()
    wcf_cfg = config.get("wcf", {})
    commands = wcf_cfg.get("commands", {})
    help_words = commands.get("help", ["帮助", "菜单"])
    list_words = commands.get("list", ["监控列表", "列表"])
    report_words = commands.get("report", ["报告", "日报", "监控"])

    # 判断指令类型
    cmd = _match_command(text, help_words, list_words, report_words)

    if not cmd:
        # 非精确指令：尝试路由到 Agent
        agent_enabled = wcf_cfg.get("agent_enabled", True)
        if agent_enabled:
            _handle_agent_message(account_id, user_id, text, wcf_cfg)
        return

    # 查找绑定
    binding = _db.get_binding_by_user(account_id, user_id)
    if not binding or not binding.get("enabled"):
        _reply_raw(account_id, user_id, "您尚未启用监控服务，请联系管理员开通。")
        return

    if cmd == "help":
        _reply_raw(account_id, user_id,
                   "可用指令：\n"
                   "• 帮助 — 显示此菜单\n"
                   "• 监控列表 — 查看已绑定的任务\n"
                   "• 报告 — 运行所有绑定的监控任务\n"
                   "• 报告 <任务名> — 运行指定任务\n\n"
                   "也可以直接用自然语言和我对话，例如：\n"
                   "「帮我创建一个监控AI新闻的任务」\n"
                   "「搜索今天的科技热点」")
        return

    if cmd == "list":
        task_ids = _db.get_binding_tasks(binding["id"])
        if not task_ids:
            _reply_raw(account_id, user_id, "当前未绑定任何监控任务。")
            return
        from modules.monitor.db import MonitorDB
        mdb = MonitorDB()
        names = []
        for tid in task_ids:
            task = mdb.get_task(tid)
            if task:
                names.append(task.get("name", tid))
        _reply_raw(account_id, user_id,
                   f"已绑定 {len(names)} 个任务：\n" + "\n".join(f"• {n}" for n in names))
        return

    if cmd == "report":
        task_name = _extract_report_target(text, report_words)
        task_ids = _db.get_binding_tasks(binding["id"])
        if not task_ids:
            _reply_raw(account_id, user_id, "当前未绑定任何监控任务。")
            return

        from modules.monitor.db import MonitorDB
        mdb = MonitorDB()

        if task_name:
            # 精确匹配任务名
            matched = []
            for tid in task_ids:
                task = mdb.get_task(tid)
                if task and task.get("name") == task_name:
                    matched.append(tid)
            if not matched:
                _reply_raw(account_id, user_id, f"未找到任务「{task_name}」。")
                return
            task_ids = matched

        # 构造 override_push_config：推送给当前联系人
        override_push = [{
            "type": "wcf",
            "account_id": account_id,
            "to_user_id": user_id,
            "context_token": binding.get("context_token", ""),
        }]

        from modules.monitor.service import get_monitor_service
        svc = get_monitor_service()
        results = []
        for tid in task_ids:
            result = svc.run_task(tid, override_push_config=override_push)
            results.append(result)

        success = sum(1 for r in results if r.get("status") == "success")
        _reply_raw(account_id, user_id,
                   f"已执行 {len(results)} 个任务，成功 {success} 个。")


def _handle_agent_message(account_id: str, user_id: str, text: str, wcf_cfg: dict):
    """将非指令消息路由到 Agent 处理。"""
    binding = _db.get_binding_by_user(account_id, user_id)
    context_token = binding.get("context_token", "") if binding else ""
    binding_id = binding["id"] if binding else ""

    # 发送"正在思考"提示
    thinking_msg = wcf_cfg.get("agent_thinking_msg", "正在思考，请稍候...")
    agent_timeout = wcf_cfg.get("agent_timeout", 60)
    try:
        _reply_raw(account_id, user_id, thinking_msg, context_token)
    except Exception:
        pass

    # 构建 Agent 上下文
    session_id = f"wcf_{account_id}_{user_id}"
    agent_context = {
        "binding_id": binding_id,
        "account_id": account_id,
        "user_id": user_id,
        "context_token": context_token,
    }

    try:
        from modules.chat.db import ChatDB
        db = ChatDB()
        if not db.get_session(session_id):
            db.create_session(session_id, title=f"微信对话 {user_id[:8]}", mode="agent")

        from modules.agent.service import AgentService
        svc = AgentService()

        full_text = ""
        import threading
        import contextvars

        result_container = []
        error_container = []

        def _run_agent():
            try:
                for chunk in svc.chat(session_id, text, context=agent_context):
                    try:
                        event = json.loads(chunk)
                        if event.get("type") == "content":
                            result_container.append(event.get("text", ""))
                    except Exception:
                        pass
            except Exception as exc:
                error_container.append(str(exc))

        # 复制当前线程的 ContextVar 上下文到新线程
        ctx = contextvars.copy_context()
        t = threading.Thread(target=ctx.run, args=(_run_agent,), daemon=True)
        t.start()
        t.join(timeout=agent_timeout)

        if t.is_alive():
            full_text = "处理超时，请稍后重试或换个更简短的问题。"
        elif error_container:
            full_text = f"处理出错：{error_container[0]}"
        else:
            full_text = "".join(result_container)

        if not full_text:
            full_text = "暂时无法回答，请稍后再试。"

    except Exception as e:
        logger.error("Agent 处理失败 %s/%s: %s", account_id, user_id, e)
        full_text = "处理您的请求时出现了错误，请稍后重试。"

    _send_long_text(account_id, user_id, full_text, context_token)


def _send_long_text(account_id: str, user_id: str, text: str,
                    context_token: str = ""):
    """将长文本分段发送，避免超出微信消息长度限制。"""
    if len(text) <= _WX_MAX_MSG_LEN:
        _reply_raw(account_id, user_id, text, context_token)
        return

    parts = []
    remaining = text
    while remaining:
        parts.append(remaining[:_WX_MAX_MSG_LEN])
        remaining = remaining[_WX_MAX_MSG_LEN:]

    for i, part in enumerate(parts):
        prefix = f"（{i + 1}/{len(parts)}）\n" if len(parts) > 1 else ""
        _reply_raw(account_id, user_id, prefix + part, context_token)
        if i < len(parts) - 1:
            time.sleep(0.5)  # 避免频率限制


def _reply_raw(account_id: str, user_id: str, text: str, context_token: str = ""):
    """发送回复消息到微信用户。

    Raises: 发送失败时抛出异常，由调用方决定是否推进游标。
    """
    if not context_token:
        binding = _db.get_binding_by_user(account_id, user_id)
        context_token = binding.get("context_token", "") if binding else ""
    client.send_text(account_id, user_id, text, context_token=context_token)


def _reply(account_id: str, user_id: str, text: str):
    """发送回复消息到微信用户（兼容旧调用）。"""
    _reply_raw(account_id, user_id, text)


def _match_command(text: str, help_words: list, list_words: list,
                   report_words: list) -> str | None:
    """匹配指令关键词，返回指令类型。"""
    # 报告指令优先匹配（可能带参数）
    for w in report_words:
        if text == w or text.startswith(w + " "):
            return "report"
    for w in list_words:
        if text == w:
            return "list"
    for w in help_words:
        if text == w:
            return "help"
    return None


def _extract_report_target(text: str, report_words: list) -> str | None:
    """从报告指令文本中提取目标任务名。"""
    for w in report_words:
        if text.startswith(w + " "):
            target = text[len(w):].strip()
            return target if target else None
    return None


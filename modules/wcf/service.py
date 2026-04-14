"""WCF 事件消费 + 指令处理服务"""

import logging

from modules.wcf import client
from modules.wcf.db import WCFDB

logger = logging.getLogger(__name__)

_db = WCFDB()


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
    """匹配并执行微信指令。

    指令范围：帮助、监控列表、报告、报告 <任务名>
    未绑定/未启用 → 回复提示
    非指令 → 忽略
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
        return  # 非指令，忽略

    # 查找绑定
    binding = _db.get_binding_by_user(account_id, user_id)
    if not binding or not binding.get("enabled"):
        _reply(account_id, user_id, "未绑定监控任务，请联系管理员。")
        return

    if cmd == "help":
        _reply(account_id, user_id,
               "可用指令：\n"
               "• 帮助 — 显示此菜单\n"
               "• 监控列表 — 查看已绑定的任务\n"
               "• 报告 — 运行所有绑定的监控任务\n"
               "• 报告 <任务名> — 运行指定任务")
        return

    if cmd == "list":
        task_ids = _db.get_binding_tasks(binding["id"])
        if not task_ids:
            _reply(account_id, user_id, "当前未绑定任何监控任务。")
            return
        from modules.monitor.db import MonitorDB
        mdb = MonitorDB()
        names = []
        for tid in task_ids:
            task = mdb.get_task(tid)
            if task:
                names.append(task.get("name", tid))
        _reply(account_id, user_id,
               f"已绑定 {len(names)} 个任务：\n" + "\n".join(f"• {n}" for n in names))
        return

    if cmd == "report":
        task_name = _extract_report_target(text, report_words)
        task_ids = _db.get_binding_tasks(binding["id"])
        if not task_ids:
            _reply(account_id, user_id, "当前未绑定任何监控任务。")
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
                _reply(account_id, user_id, f"未找到任务「{task_name}」。")
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
        _reply(account_id, user_id,
               f"已执行 {len(results)} 个任务，成功 {success} 个。")


def _reply(account_id: str, user_id: str, text: str):
    """发送回复消息到微信用户。

    Raises: 发送失败时抛出异常，由调用方决定是否推进游标。
    """
    binding = _db.get_binding_by_user(account_id, user_id)
    context_token = binding.get("context_token", "") if binding else ""
    client.send_text(account_id, user_id, text, context_token=context_token)


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

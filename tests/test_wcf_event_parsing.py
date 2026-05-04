"""测试 WCF 事件解析 + 调度窗口 + 边界值

覆盖:
- wcfLink API 事件格式解析
- _is_task_due 双调度窗口
- WCFService 类别名
- 恶意/脏数据输入
"""

import json
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


# ── 事件解析 ────────────────────────────────────────────────

def parse_wcf_event(evt):
    """模拟 scheduler.py _poll_wcf_events 中的事件过滤逻辑"""
    evt_id = evt.get("id", 0)
    evt_type = evt.get("event_type", "")
    direction = evt.get("direction", "")

    if direction != "inbound" or evt_type != "text":
        return None  # skip

    account_id = evt.get("account_id", "")
    user_id = evt.get("from_user_id", "")
    body_text = evt.get("body_text", "")

    if not account_id or not user_id or not body_text.strip():
        return None  # skip

    return {
        "id": evt_id,
        "account_id": account_id,
        "user_id": user_id,
        "body_text": body_text,
    }


class TestWCFEventParsing:
    """WCF 事件格式解析（匹配修复后的逻辑）"""

    def test_normal_inbound_text(self):
        evt = {
            "id": 75, "event_type": "text", "direction": "inbound",
            "account_id": "84c@im.bot", "from_user_id": "user@im.wechat",
            "body_text": "今日新闻",
        }
        result = parse_wcf_event(evt)
        assert result is not None
        assert result["body_text"] == "今日新闻"

    def test_outbound_skipped(self):
        evt = {"id": 1, "event_type": "text", "direction": "outbound",
               "account_id": "a@im.bot", "from_user_id": "u@im.wechat", "body_text": "hi"}
        assert parse_wcf_event(evt) is None

    def test_wrong_event_type(self):
        evt = {"id": 2, "event_type": "image", "direction": "inbound",
               "account_id": "a@im.bot", "from_user_id": "u@im.wechat", "body_text": ""}
        assert parse_wcf_event(evt) is None

    def test_old_format_message_text_skipped(self):
        """旧代码用 event_type == 'message/text'，现在应跳过"""
        evt = {"id": 3, "event_type": "message/text", "direction": "inbound",
               "account_id": "a@im.bot", "from_user_id": "u@im.wechat", "body_text": "hi"}
        assert parse_wcf_event(evt) is None

    def test_empty_body_text_skipped(self):
        evt = {"id": 4, "event_type": "text", "direction": "inbound",
               "account_id": "a@im.bot", "from_user_id": "u@im.wechat", "body_text": "   "}
        assert parse_wcf_event(evt) is None

    def test_missing_account_id(self):
        evt = {"id": 5, "event_type": "text", "direction": "inbound",
               "account_id": "", "from_user_id": "u@im.wechat", "body_text": "hi"}
        assert parse_wcf_event(evt) is None

    def test_missing_user_id(self):
        evt = {"id": 6, "event_type": "text", "direction": "inbound",
               "account_id": "a@im.bot", "from_user_id": "", "body_text": "hi"}
        assert parse_wcf_event(evt) is None

    def test_missing_fields_returns_none(self):
        assert parse_wcf_event({}) is None
        assert parse_wcf_event({"id": 99}) is None

    def test_unicode_and_special_chars(self):
        evt = {"id": 7, "event_type": "text", "direction": "inbound",
               "account_id": "a@im.bot", "from_user_id": "u@im.wechat",
               "body_text": "<script>alert(1)</script> \x00 null byte 🎉"}
        result = parse_wcf_event(evt)
        assert result is not None
        assert "<script>" in result["body_text"]

    def test_very_long_body_text(self):
        evt = {"id": 8, "event_type": "text", "direction": "inbound",
               "account_id": "a@im.bot", "from_user_id": "u@im.wechat",
               "body_text": "A" * 100000}
        result = parse_wcf_event(evt)
        assert result is not None
        assert len(result["body_text"]) == 100000

    def test_none_values_in_event(self):
        evt = {"id": None, "event_type": None, "direction": None,
               "account_id": None, "from_user_id": None, "body_text": None}
        assert parse_wcf_event(evt) is None


class TestScheduleDueLogic:
    """_is_task_due 双调度窗口测试"""

    @staticmethod
    def _is_task_due(task, schedules, now=None):
        """模拟 MonitorService._is_task_due（修复后版本）"""
        now = now or datetime.now()
        today = now.strftime("%Y-%m-%d")

        schedule = task.get("schedule", "daily_morning")
        target_time = schedules.get(schedule, "08:00")
        hour, minute = map(int, target_time.split(":"))

        target_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < target_dt:
            return False
        if (now - target_dt).total_seconds() >= 3600:
            return False

        last_run = task.get("last_run_at") or ""
        if isinstance(last_run, str) and last_run.startswith(today):
            try:
                last_dt = datetime.strptime(last_run, "%Y-%m-%d %H:%M:%S")
                last_slot = "daily_evening" if last_dt.hour >= 14 else "daily_morning"
                if last_slot == schedule:
                    return False
            except (ValueError, TypeError):
                return False

        return True

    def test_morning_slot_due_at_08_05(self):
        now = datetime(2026, 5, 4, 8, 5, 0)
        task = {"schedule": "daily_morning", "last_run_at": ""}
        assert self._is_task_due(task, {"daily_morning": "08:00", "daily_evening": "20:00"}, now) is True

    def test_evening_slot_due_at_20_05(self):
        now = datetime(2026, 5, 4, 20, 5, 0)
        task = {"schedule": "daily_evening", "last_run_at": ""}
        assert self._is_task_due(task, {"daily_morning": "08:00", "daily_evening": "20:00"}, now) is True

    def test_morning_already_ran_same_slot(self):
        """早上已执行 → 早上不再触发"""
        now = datetime(2026, 5, 4, 8, 10, 0)
        task = {"schedule": "daily_morning", "last_run_at": "2026-05-04 08:03:00"}
        assert self._is_task_due(task, {"daily_morning": "08:00", "daily_evening": "20:00"}, now) is False

    def test_morning_ran_but_evening_still_due(self):
        """早上执行过 → 晚上仍可触发（关键修复点）"""
        now = datetime(2026, 5, 4, 20, 10, 0)
        task = {"schedule": "daily_evening", "last_run_at": "2026-05-04 08:03:00"}
        assert self._is_task_due(task, {"daily_morning": "08:00", "daily_evening": "20:00"}, now) is True

    def test_both_ran_today(self):
        """早晚都执行过 → 两个都不再触发"""
        now_m = datetime(2026, 5, 4, 8, 15, 0)
        now_e = datetime(2026, 5, 4, 20, 15, 0)
        task_m = {"schedule": "daily_morning", "last_run_at": "2026-05-04 08:05:00"}
        task_e = {"schedule": "daily_evening", "last_run_at": "2026-05-04 20:05:00"}
        schedules = {"daily_morning": "08:00", "daily_evening": "20:00"}
        assert self._is_task_due(task_m, schedules, now_m) is False
        assert self._is_task_due(task_e, schedules, now_e) is False

    def test_before_target_time(self):
        now = datetime(2026, 5, 4, 7, 30, 0)
        task = {"schedule": "daily_morning", "last_run_at": ""}
        assert self._is_task_due(task, {"daily_morning": "08:00"}, now) is False

    def test_past_one_hour_window(self):
        now = datetime(2026, 5, 4, 9, 30, 0)
        task = {"schedule": "daily_morning", "last_run_at": ""}
        assert self._is_task_due(task, {"daily_morning": "08:00"}, now) is False

    def test_corrupt_last_run_at(self):
        """garbage 不以今日日期开头 → 视为未执行，返回 True"""
        now = datetime(2026, 5, 4, 8, 10, 0)
        task = {"schedule": "daily_morning", "last_run_at": "garbage"}
        assert self._is_task_due(task, {"daily_morning": "08:00"}, now) is True

    def test_none_last_run(self):
        now = datetime(2026, 5, 4, 8, 10, 0)
        task = {"schedule": "daily_morning", "last_run_at": None}
        assert self._is_task_due(task, {"daily_morning": "08:00"}, now) is True


class TestWCFServiceAlias:
    """验证 WCFService = AgentService 别名存在"""

    def test_import_wcf_service(self):
        from modules.wcf.service import WCFService, AgentService
        assert WCFService is AgentService

    def test_instantiate_wcf_service(self):
        from modules.wcf.service import WCFService
        svc = WCFService()
        assert hasattr(svc, "chat")
        assert hasattr(svc, "db")

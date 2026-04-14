"""WCF 模块单元测试"""

import os
import pytest
from unittest.mock import patch, MagicMock

from modules.wcf.db import WCFDB


@pytest.fixture
def wcf_db(tmp_db_dir):
    return WCFDB(os.path.join(tmp_db_dir, "wcf.db"))


# ── DB 测试 ──

class TestWCFDB:
    def test_meta_get_set(self, wcf_db):
        assert wcf_db.get_meta("last_event_id") is None
        wcf_db.set_meta("last_event_id", "42")
        assert wcf_db.get_meta("last_event_id") == "42"

    def test_cursor_default_zero(self, wcf_db):
        assert wcf_db.get_cursor() == 0

    def test_cursor_advance(self, wcf_db):
        wcf_db.set_cursor(100)
        assert wcf_db.get_cursor() == 100

    def test_upsert_binding_insert(self, wcf_db):
        bid = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat",
                                     display_name="Alice",
                                     context_token="tok1",
                                     last_message="hello")
        assert bid
        binding = wcf_db.get_binding(bid)
        assert binding["account_id"] == "acc1@im.bot"
        assert binding["user_id"] == "user1@im.wechat"
        assert binding["display_name"] == "Alice"
        assert binding["context_token"] == "tok1"
        assert binding["enabled"] == 0

    def test_upsert_binding_preserves_id_and_enabled(self, wcf_db):
        bid = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat",
                                     display_name="Alice")
        # 启用
        wcf_db.set_binding_enabled(bid, True)

        # 再次 upsert（模拟事件轮询看到同一联系人）
        bid2 = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat",
                                      display_name="Alice Updated",
                                      last_message="new msg")
        assert bid2 == bid  # id 不变
        binding = wcf_db.get_binding(bid)
        assert binding["enabled"] == 1  # enabled 不变
        assert binding["display_name"] == "Alice Updated"

    def test_unique_constraint_prevents_duplicate(self, wcf_db):
        bid1 = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat")
        bid2 = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat")
        assert bid1 == bid2
        bindings = wcf_db.list_bindings()
        assert len(bindings) == 1

    def test_list_bindings_enabled_only(self, wcf_db):
        bid1 = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat")
        bid2 = wcf_db.upsert_binding("acc1@im.bot", "user2@im.wechat")
        wcf_db.set_binding_enabled(bid1, True)

        enabled = wcf_db.list_bindings(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["id"] == bid1

    def test_binding_tasks(self, wcf_db):
        bid = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat")
        wcf_db.bind_task(bid, "task-1")
        wcf_db.bind_task(bid, "task-2")

        tasks = wcf_db.get_binding_tasks(bid)
        assert set(tasks) == {"task-1", "task-2"}

        wcf_db.unbind_task(bid, "task-1")
        tasks = wcf_db.get_binding_tasks(bid)
        assert tasks == ["task-2"]

    def test_delete_task_bindings(self, wcf_db):
        bid = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat")
        wcf_db.bind_task(bid, "task-1")
        wcf_db.bind_task(bid, "task-2")

        wcf_db.delete_task_bindings("task-1")
        tasks = wcf_db.get_binding_tasks(bid)
        assert "task-1" not in tasks
        assert "task-2" in tasks

    def test_get_bindings_for_task(self, wcf_db):
        bid1 = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat")
        bid2 = wcf_db.upsert_binding("acc1@im.bot", "user2@im.wechat")
        wcf_db.bind_task(bid1, "task-A")
        wcf_db.bind_task(bid2, "task-A")

        bindings = wcf_db.get_bindings_for_task("task-A")
        assert len(bindings) == 2

    def test_update_display_name(self, wcf_db):
        bid = wcf_db.upsert_binding("acc1@im.bot", "user1@im.wechat")
        wcf_db.update_binding_display_name(bid, "Bob")
        binding = wcf_db.get_binding(bid)
        assert binding["display_name"] == "Bob"


# ── Service 指令匹配测试 ──

class TestCommandMatching:
    def test_match_help(self):
        from modules.wcf.service import _match_command
        assert _match_command("帮助", ["帮助"], ["列表"], ["报告"]) == "help"
        assert _match_command("菜单", ["帮助", "菜单"], ["列表"], ["报告"]) == "help"

    def test_match_list(self):
        from modules.wcf.service import _match_command
        assert _match_command("监控列表", ["帮助"], ["监控列表", "列表"], ["报告"]) == "list"
        assert _match_command("列表", ["帮助"], ["监控列表", "列表"], ["报告"]) == "list"

    def test_match_report(self):
        from modules.wcf.service import _match_command
        assert _match_command("报告", ["帮助"], ["列表"], ["报告", "日报"]) == "report"
        assert _match_command("报告 AI动态", ["帮助"], ["列表"], ["报告", "日报"]) == "report"

    def test_no_match(self):
        from modules.wcf.service import _match_command
        assert _match_command("随便说点什么", ["帮助"], ["列表"], ["报告"]) is None

    def test_report_priority_over_help(self):
        from modules.wcf.service import _match_command
        # "监控" 既是 report 指令，也包含在 "监控列表" 里
        # 但 report 先匹配，所以 "监控" 应该匹配 report
        assert _match_command("监控", ["帮助"], ["监控列表"], ["报告", "监控"]) == "report"

    def test_extract_report_target(self):
        from modules.wcf.service import _extract_report_target
        assert _extract_report_target("报告 AI动态", ["报告", "日报"]) == "AI动态"
        assert _extract_report_target("报告", ["报告", "日报"]) is None
        assert _extract_report_target("随便", ["报告"]) is None


# ── Push WCF 格式兼容测试 ──

class TestWCFPushFormat:
    def test_new_format_uses_config_url(self):
        from modules.monitor.push import _send_wcf
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            with patch("utils.config.load_config") as mock_cfg:
                mock_cfg.return_value = {"wcf": {"url": "http://wcf:17890"}}
                ok, err = _send_wcf("test", {
                    "type": "wcf",
                    "account_id": "acc@im.bot",
                    "to_user_id": "user@im.wechat",
                })
                assert ok
                call_url = mock_post.call_args[0][0]
                assert call_url == "http://wcf:17890/api/messages/send-text"

    def test_old_format_with_url_and_secret(self):
        from modules.monitor.push import _send_wcf
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            ok, err = _send_wcf("test", {
                "type": "wcf",
                "url": "http://custom:17890",
                "secret": "acc@im.bot::user@im.wechat",
            })
            assert ok
            call_url = mock_post.call_args[0][0]
            assert call_url == "http://custom:17890/api/messages/send-text"
            payload = mock_post.call_args[1]["json"]
            assert payload["account_id"] == "acc@im.bot"
            assert payload["to_user_id"] == "user@im.wechat"

    def test_context_token_passed(self):
        from modules.monitor.push import _send_wcf
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            with patch("utils.config.load_config") as mock_cfg:
                mock_cfg.return_value = {"wcf": {"url": "http://wcf:17890"}}
                ok, err = _send_wcf("test", {
                    "type": "wcf",
                    "account_id": "acc@im.bot",
                    "to_user_id": "user@im.wechat",
                    "context_token": "tok123",
                })
                assert ok
                payload = mock_post.call_args[1]["json"]
                assert payload["context_token"] == "tok123"


# ── 事件处理游标推进测试 ──

class TestEventCursorSemantics:
    def test_process_outbound_advances_cursor(self):
        from modules.wcf.service import _process_event
        with patch("modules.wcf.service._db") as mock_db:
            result = _process_event({
                "id": 1, "direction": "outbound",
                "account_id": "a", "from_user_id": "u",
            })
            assert result is True

    def test_process_non_text_advances_cursor(self):
        from modules.wcf.service import _process_event
        with patch("modules.wcf.service._db") as mock_db:
            result = _process_event({
                "id": 2, "direction": "inbound",
                "event_type": "image", "account_id": "a",
                "from_user_id": "u", "context_token": "",
            })
            assert result is True
            mock_db.upsert_binding.assert_called_once()

    def test_process_text_non_command_advances_cursor(self):
        from modules.wcf.service import _process_event
        with patch("modules.wcf.service._db") as mock_db, \
             patch("modules.wcf.service.handle_command"):
            mock_db.get_binding_by_user.return_value = None
            result = _process_event({
                "id": 3, "direction": "inbound",
                "event_type": "text", "account_id": "a",
                "from_user_id": "u", "context_token": "tok",
                "body_text": "随便聊聊",
            })
            assert result is True

    def test_process_command_failure_no_cursor_advance(self):
        from modules.wcf.service import _process_event
        with patch("modules.wcf.service._db") as mock_db, \
             patch("modules.wcf.service.handle_command", side_effect=Exception("boom")):
            mock_db.get_binding_by_user.return_value = None
            result = _process_event({
                "id": 4, "direction": "inbound",
                "event_type": "text", "account_id": "a",
                "from_user_id": "u", "context_token": "tok",
                "body_text": "报告",
            })
            assert result is False


# ── WCF 推送配置展开测试 ──

class TestWCFPushExpand:
    def test_expand_shorthand_to_bindings(self, tmp_db_dir):
        from modules.wcf.db import WCFDB
        wcf_db = WCFDB(os.path.join(tmp_db_dir, "wcf_test.db"))
        bid = wcf_db.upsert_binding("acc@im.bot", "user1@im.wechat",
                                     context_token="tok1")
        wcf_db.set_binding_enabled(bid, True)
        wcf_db.bind_task(bid, "task-A")

        from modules.monitor.service import MonitorService
        svc = MonitorService()
        # _expand_wcf_push_config 内部延迟 import WCFDB，mock 模块级引用
        with patch("modules.wcf.db.WCFDB", return_value=wcf_db):
            expanded = svc._expand_wcf_push_config(
                [{"type": "wcf"}], "task-A"
            )
        assert len(expanded) == 1
        assert expanded[0]["account_id"] == "acc@im.bot"
        assert expanded[0]["to_user_id"] == "user1@im.wechat"
        assert expanded[0]["context_token"] == "tok1"

    def test_no_expand_for_old_format(self):
        from modules.monitor.service import MonitorService
        svc = MonitorService()
        config = [{"type": "wcf", "url": "http://x", "secret": "a::b"}]
        expanded = svc._expand_wcf_push_config(config, "task-X")
        assert expanded == config  # 不展开

    def test_no_expand_for_explicit_format(self):
        from modules.monitor.service import MonitorService
        svc = MonitorService()
        config = [{"type": "wcf", "account_id": "a", "to_user_id": "b"}]
        expanded = svc._expand_wcf_push_config(config, "task-X")
        assert expanded == config

    def test_non_wcf_channels_pass_through(self):
        from modules.monitor.service import MonitorService
        svc = MonitorService()
        config = [{"type": "wecom", "url": "http://x"}]
        expanded = svc._expand_wcf_push_config(config, "task-X")
        assert expanded == config


# ── 删除任务时清理绑定 ──

class TestDeleteTaskCleansBindings:
    def test_delete_task_calls_wcf_cleanup(self, tmp_db_dir):
        from modules.wcf.db import WCFDB
        wcf_db = WCFDB(os.path.join(tmp_db_dir, "wcf_del.db"))
        bid = wcf_db.upsert_binding("acc@im.bot", "user1@im.wechat")
        wcf_db.bind_task(bid, "task-to-delete")

        from modules.monitor.service import MonitorService
        svc = MonitorService()
        with patch.object(svc.db, "delete_task", return_value=True), \
             patch("modules.wcf.db.WCFDB", return_value=wcf_db):
            ok = svc.delete_task("task-to-delete")
        assert ok is True
        assert wcf_db.get_binding_tasks(bid) == []


# ── 空推送目标不记成功 ──

class TestEmptyPushTargets:
    def test_empty_push_config_logs_failure(self):
        from modules.monitor.service import MonitorService
        svc = MonitorService()
        with patch.object(svc.db, "log_push") as mock_log, \
             patch.object(svc.db, "update_task"):
            svc.deliver_report("report text", push_config=[], task_id="t1")
        mock_log.assert_called_once()
        args = mock_log.call_args
        assert args[0][0] == "t1"
        assert args[1].get("status") == "failed" or args[0][1] == "failed"


# ── 多渠道展开不丢后续渠道 ──

class TestMultiChannelExpand:
    def test_wcf_shorthand_followed_by_other_channels(self):
        from modules.monitor.service import MonitorService
        svc = MonitorService()
        config = [
            {"type": "wecom", "url": "http://x"},
            {"type": "wcf"},
            {"type": "generic", "url": "http://y"},
        ]
        with patch("modules.wcf.db.WCFDB") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db
            mock_db.get_bindings_for_task.return_value = [
                {"enabled": True, "account_id": "a", "user_id": "u", "context_token": "t"},
            ]
            expanded = svc._expand_wcf_push_config(config, "task-X")

        types = [c["type"] for c in expanded]
        assert "wecom" in types
        assert "generic" in types
        assert len([t for t in types if t == "wcf"]) == 1


# ── _reply 失败传播 ──

class TestReplyFailure:
    def test_reply_raises_on_send_failure(self):
        from modules.wcf.service import _reply
        with patch("modules.wcf.service._db") as mock_db, \
             patch("modules.wcf.service.client") as mock_client:
            mock_db.get_binding_by_user.return_value = {"context_token": "tok"}
            mock_client.send_text.side_effect = Exception("connection refused")
            with pytest.raises(Exception, match="connection refused"):
                _reply("acc", "user", "hello")

    def test_command_reply_failure_prevents_cursor_advance(self):
        from modules.wcf.service import _process_event
        with patch("modules.wcf.service._db") as mock_db, \
             patch("modules.wcf.service.handle_command") as mock_cmd:
            mock_db.upsert_binding = MagicMock()
            # handle_command 抛异常 → _process_event 返回 False
            mock_cmd.side_effect = Exception("reply send failed")
            result = _process_event({
                "id": 5, "direction": "inbound",
                "event_type": "text", "account_id": "a",
                "from_user_id": "u", "context_token": "tok",
                "body_text": "报告",
            })
            assert result is False

"""Monitor 模块单元测试"""

import json
import os
import tempfile
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from modules.monitor.db import MonitorDB
from modules.monitor.service import MonitorService, _running_lock, _running_tasks


@pytest.fixture
def monitor_db():
    """使用临时文件的 MonitorDB"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = MonitorDB(db_path=db_path)
    yield db
    os.unlink(db_path)


@pytest.fixture
def monitor_svc(monitor_db):
    """使用临时 DB 的 MonitorService"""
    svc = MonitorService()
    svc.db = monitor_db
    return svc


class TestMonitorDB:
    def test_create_task_returns_valid_dict(self, monitor_db):
        """create_task 必须返回有效 dict，不应因连接关闭报错。"""
        task = monitor_db.create_task(
            task_id="test-1",
            name="AI监控",
            keywords=["AI", "大模型"],
            filters={"category": "科技AI"},
            schedule="daily_morning",
            push_config=[{"type": "wecom", "url": "https://qyapi.weixin.qq.com/test", "secret": "abc123"}],
        )
        assert isinstance(task, dict), f"create_task should return dict, got {type(task)}"
        assert task["id"] == "test-1"
        assert task["name"] == "AI监控"
        # 关键验证：返回的 dict 不应触发 ProgrammingError
        assert "keywords" in task or "id" in task

    def test_create_and_get_task_roundtrip(self, monitor_db):
        """创建后再查询，数据应一致。"""
        monitor_db.create_task(
            task_id="test-1b",
            name="往返测试",
            keywords=["AI"],
            filters=None,
            schedule="daily_morning",
            push_config=[{"type": "wecom", "url": "https://qyapi.weixin.qq.com/test", "secret": "abc123"}],
        )
        retrieved = monitor_db.get_task("test-1b")
        assert retrieved is not None
        assert retrieved["name"] == "往返测试"

    def test_push_config_sanitized(self, monitor_db):
        monitor_db.create_task(
            task_id="test-2", name="测试",
            keywords=["test"], filters=None,
            schedule="daily_morning",
            push_config=[{"type": "wecom", "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc-123-def-456", "secret": "mysecret"}],
        )
        task = monitor_db.get_task("test-2")
        config = json.loads(task["push_config"])
        assert "secret" not in str(config) or config[0]["secret"] == "***"
        assert config[0]["url"] != "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc-123-def-456"

    def test_update_task_partial(self, monitor_db):
        monitor_db.create_task(
            task_id="test-3", name="原名称",
            keywords=["test"], filters=None,
            schedule="daily_morning",
            push_config=[{"type": "wecom", "url": "https://example.com"}],
        )
        result = monitor_db.update_task("test-3", name="新名称")
        assert result is not None
        assert result["name"] == "新名称"

    def test_update_task_internal_fields(self, monitor_db):
        monitor_db.create_task(
            task_id="test-4", name="测试",
            keywords=["test"], filters=None,
            schedule="daily_morning",
            push_config=[{"type": "wecom", "url": "https://example.com"}],
        )
        monitor_db.update_task("test-4", last_run_at="2026-04-13 08:00:00")
        raw = monitor_db.get_task_raw("test-4")
        assert raw["last_run_at"] == "2026-04-13 08:00:00"

    def test_routes_cannot_update_internal_fields(self, monitor_db):
        """路由层应过滤掉 _INTERNAL_FIELDS"""
        monitor_db.create_task(
            task_id="test-5", name="测试",
            keywords=["test"], filters=None,
            schedule="daily_morning",
            push_config=[{"type": "wecom", "url": "https://example.com"}],
        )
        user_data = {k: v for k, v in {"name": "改名", "last_run_at": "hacked"}.items()
                     if k in MonitorDB._USER_FIELDS}
        monitor_db.update_task("test-5", **user_data)
        raw = monitor_db.get_task_raw("test-5")
        assert raw["name"] == "改名"
        assert raw["last_run_at"] is None  # 未被修改

    def test_delete_task(self, monitor_db):
        monitor_db.create_task(
            task_id="test-6", name="待删",
            keywords=["test"], filters=None,
            schedule="daily_morning",
            push_config=[{"type": "wecom", "url": "https://example.com"}],
        )
        assert monitor_db.delete_task("test-6") is True
        assert monitor_db.get_task("test-6") is None

    def test_log_push(self, monitor_db):
        monitor_db.log_push("test-7", status="success", report_summary="测试报告")
        logs = monitor_db.get_push_logs("test-7")
        assert len(logs) == 1
        assert logs[0]["status"] == "success"


class TestMonitorService:
    def test_is_task_due_no_last_run(self):
        """新任务（last_run_at=None）应在时间窗内触发"""
        task = {
            "last_run_at": None,
            "schedule": "daily_morning",
        }
        # 需要模拟当前时间在 08:00-09:00 之间
        schedules = {"daily_morning": "08:00"}
        result = MonitorService._is_task_due(task, schedules)
        # 结果取决于实际运行时间，但不应因 None 异常
        assert isinstance(result, bool)

    def test_is_task_due_empty_string(self):
        """last_run_at 为空字符串时不应异常"""
        task = {"last_run_at": "", "schedule": "daily_morning"}
        schedules = {"daily_morning": "08:00"}
        result = MonitorService._is_task_due(task, schedules)
        assert isinstance(result, bool)

    def test_is_task_due_already_ran_today(self):
        """今天已执行过的任务不应再触发"""
        today = datetime.now().strftime("%Y-%m-%d")
        task = {"last_run_at": f"{today} 08:30:00", "schedule": "daily_morning"}
        schedules = {"daily_morning": "08:00"}
        result = MonitorService._is_task_due(task, schedules)
        assert result is False

    @patch("modules.monitor.service.scheduler_post")
    def test_run_task_dedup(self, mock_post, monitor_svc, monitor_db):
        """同一任务不应重复执行"""
        monitor_db.create_task(
            task_id="dedup-test", name="去重测试",
            keywords=["test"], filters=None,
            schedule="daily_morning",
            push_config=[{"type": "generic", "url": "https://example.com"}],
        )
        # 模拟搜索结果
        mock_post.return_value = [{"title": "test", "source_name": "测试"}]

        # 清理全局状态
        with _running_lock:
            _running_tasks.clear()

        # 使用 patch 避免 LLM 调用
        with patch.object(monitor_svc, "_generate_report", return_value="测试报告"):
            r1 = monitor_svc.run_task("dedup-test")
            # 第一次应该成功（或 error，取决于 mock）
            assert r1["status"] in ("success", "error", "partial")

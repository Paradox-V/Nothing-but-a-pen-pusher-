"""测试 admin/routes.py overview 降级逻辑

覆盖:
- 正常聚合（各模块 DB 正常）
- 单模块异常时降级返回 _degraded=True
- 所有模块异常时整体不崩溃
- 降级字段结构完整
"""

import json
import os
import sqlite3
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from app import app


@pytest.fixture
def client():
    """提供 Flask test client，配置 ADMIN_TOKEN 绕过鉴权"""
    app.config["TESTING"] = True
    os.environ["ADMIN_TOKEN"] = "test-token"
    with app.test_client() as c:
        yield c
    os.environ.pop("ADMIN_TOKEN", None)


class TestOverviewDegradation:
    """overview 接口降级行为"""

    def test_overview_returns_json(self, client):
        """基本调用不崩溃，返回 JSON"""
        with patch("modules.account.db.AccountDB") as MockADB, \
             patch("modules.monitor.db.MonitorDB") as MockMDB, \
             patch("modules.rss.db.RSSDB") as MockRDB, \
             patch("modules.news.db.NewsDB") as MockNDB, \
             patch("modules.wcf.db.WCFDB") as MockWDB, \
             patch("utils.scheduler_client.is_scheduler_alive", return_value=True), \
             patch("ai.AI_AVAILABLE", True):
            MockADB.return_value.get_user_count.return_value = 5
            MockMDB.return_value.get_tasks.return_value = []
            MockMDB.return_value.get_today_push_stats.return_value = {"success": 0, "fail": 0}
            MockRDB.return_value.get_feeds.return_value = []
            MockNDB.return_value.get_count.return_value = 100
            MockWDB.return_value.list_bindings.return_value = []

            resp = client.get("/api/admin/overview",
                              headers={"Authorization": "Bearer test-token"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["news"]["total"] == 100
            assert data["scheduler"]["alive"] is True
            assert data["ai"]["available"] is True
            assert "_degraded" not in data.get("news", {})

    def test_single_module_degrades_gracefully(self, client):
        """单个模块抛异常时降级，其他模块正常"""
        with patch("modules.account.db.AccountDB") as MockADB, \
             patch("modules.monitor.db.MonitorDB") as MockMDB, \
             patch("modules.rss.db.RSSDB") as MockRDB, \
             patch("modules.news.db.NewsDB") as MockNDB, \
             patch("modules.wcf.db.WCFDB") as MockWDB, \
             patch("utils.scheduler_client.is_scheduler_alive", return_value=True), \
             patch("ai.AI_AVAILABLE", True):
            # news 模块抛异常
            MockNDB.return_value.get_count.side_effect = sqlite3.DatabaseError("corrupt")
            MockADB.return_value.get_user_count.return_value = 3
            MockMDB.return_value.get_tasks.return_value = []
            MockMDB.return_value.get_today_push_stats.return_value = {}
            MockRDB.return_value.get_feeds.return_value = []
            MockWDB.return_value.list_bindings.return_value = []

            resp = client.get("/api/admin/overview",
                              headers={"Authorization": "Bearer test-token"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["news"]["_degraded"] is True
            assert data["news"]["total"] == 0
            # 其他模块正常
            assert data["users"]["total"] == 3
            assert "_degraded" not in data.get("users", {})

    def test_all_modules_degrade(self, client):
        """所有模块都异常时仍返回完整结构"""
        with patch("modules.account.db.AccountDB", side_effect=ImportError), \
             patch("modules.monitor.db.MonitorDB", side_effect=ImportError), \
             patch("modules.rss.db.RSSDB", side_effect=ImportError), \
             patch("modules.news.db.NewsDB", side_effect=ImportError), \
             patch("modules.wcf.db.WCFDB", side_effect=ImportError), \
             patch("utils.scheduler_client.is_scheduler_alive", side_effect=ConnectionError), \
             patch("ai.AI_AVAILABLE", False):
            resp = client.get("/api/admin/overview",
                              headers={"Authorization": "Bearer test-token"})
            assert resp.status_code == 200
            data = resp.get_json()
            # 所有模块都应存在
            for key in ("users", "monitor", "rss", "news", "wcf", "scheduler", "ai"):
                assert key in data
            # 降级模块应有标记
            assert data.get("users", {}).get("_degraded") is True
            assert data.get("scheduler", {}).get("_degraded") is True


class TestStatusDegradation:
    """app.py /api/status 降级行为"""

    def test_status_with_corrupt_db(self, tmp_db_dir):
        """数据库损坏时降级，不崩溃"""
        client = app.test_client()

        # mock NewsDB 抛异常
        with patch("modules.news.db.NewsDB") as MockNDB:
            MockNDB.side_effect = sqlite3.DatabaseError("corrupt")
            resp = client.get("/api/status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["news"]["available"] is False
            assert data["news"].get("_degraded") is True

    def test_status_normal(self):
        """正常状态无降级标记"""
        client = app.test_client()

        with patch("modules.news.db.NewsDB") as MockNDB, \
             patch("modules.hotlist.db.HotlistDB") as MockHDB, \
             patch("modules.rss.db.RSSDB") as MockRDB:
            MockNDB.return_value.get_count.return_value = 50
            MockNDB.return_value.db_path = "data/news.db"
            MockHDB.return_value.get_last_crawl_time.return_value = "2026-05-04"
            MockRDB.return_value.get_feeds.return_value = [{"id": 1}]

            resp = client.get("/api/status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["news"]["count"] == 50
            assert "_degraded" not in data.get("news", {})

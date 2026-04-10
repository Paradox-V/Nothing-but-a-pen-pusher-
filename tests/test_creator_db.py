"""CreatorDB 持久化测试"""

import json


class TestCreatorDB:
    def test_save_and_get_framework(self, creator_db):
        fw = {
            "id": "abc123",
            "title": "测试标题",
            "status": "draft",
            "chat_history": [{"role": "user", "content": "hello"}],
            "images": ["http://img/1.jpg"],
        }
        creator_db.save_framework(fw)

        result = creator_db.get_framework("abc123")
        assert result is not None
        assert result["title"] == "测试标题"
        assert result["status"] == "draft"
        assert len(result["chat_history"]) == 1
        assert len(result["images"]) == 1

    def test_update_framework(self, creator_db):
        fw = {"id": "xyz", "title": "初始", "status": "draft"}
        creator_db.save_framework(fw)

        fw["title"] = "更新后"
        fw["status"] = "confirmed"
        creator_db.save_framework(fw)

        result = creator_db.get_framework("xyz")
        assert result["title"] == "更新后"
        assert result["status"] == "confirmed"

    def test_task_lifecycle(self, creator_db):
        creator_db.save_framework({"id": "fw1", "title": "T"})
        creator_db.create_task("task1", "fw1")

        task = creator_db.get_task("task1")
        assert task["status"] == "running"
        assert task["framework_id"] == "fw1"

        creator_db.update_task("task1", status="completed", progress="完成",
                               result={"article": "text", "images": []})

        task = creator_db.get_task("task1")
        assert task["status"] == "completed"
        assert task["result"]["article"] == "text"

    def test_nonexistent_returns_none(self, creator_db):
        assert creator_db.get_framework("nope") is None
        assert creator_db.get_task("nope") is None

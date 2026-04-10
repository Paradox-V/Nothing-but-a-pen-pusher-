"""HotlistDB 核心测试：insert_batch 计数准确性"""

from datetime import datetime


def _make_hot_item(title, platform="weibo", rank=1):
    return {
        "title": title,
        "url": f"http://x/{title}",
        "platform": platform,
        "platform_name": platform,
        "hot_rank": rank,
        "hot_score": "100",
    }


class TestHotlistInsertBatch:
    def test_insert_new_items(self, hotlist_db):
        items = [_make_hot_item("热搜1"), _make_hot_item("热搜2")]
        result = hotlist_db.insert_batch(items, "2026-01-01 12:00:00")
        assert result["new"] == 2
        assert result["updated"] == 0
        assert result["total"] == 2

    def test_update_existing(self, hotlist_db):
        """重复 (title, platform) 应更新而非新增"""
        hotlist_db.insert_batch([_make_hot_item("热搜A")], "2026-01-01 12:00:00")
        result = hotlist_db.insert_batch(
            [_make_hot_item("热搜A", rank=2)],  # rank 变化
            "2026-01-01 13:00:00",
        )
        assert result["new"] == 0
        assert result["updated"] == 1

    def test_mixed_new_and_update(self, hotlist_db):
        hotlist_db.insert_batch([_make_hot_item("旧热搜")], "2026-01-01 12:00:00")

        items = [_make_hot_item("旧热搜"), _make_hot_item("新热搜")]
        result = hotlist_db.insert_batch(items, "2026-01-01 13:00:00")
        assert result["new"] == 1
        assert result["updated"] == 1

    def test_appear_count_increments(self, hotlist_db):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hotlist_db.insert_batch([_make_hot_item("持续热搜")], now)
        hotlist_db.insert_batch([_make_hot_item("持续热搜")], now)

        items = hotlist_db.get_items(hours=1)["items"]
        assert len(items) == 1
        assert items[0]["appear_count"] == 2

"""RSSDB 核心测试：insert_items 计数准确性"""


class TestRSSInsertItems:
    def test_insert_new_items(self, rss_db):
        rss_db.add_feed("测试源", "http://example.com/feed.xml")
        items = [
            {"title": "文章1", "feed_id": "test", "url": "http://x/1"},
            {"title": "文章2", "feed_id": "test", "url": "http://x/2"},
        ]
        inserted = rss_db.insert_items(items, "2026-01-01T12:00:00")
        assert inserted == 2

    def test_ignore_duplicates(self, rss_db):
        rss_db.add_feed("测试源", "http://example.com/feed.xml")
        items = [
            {"title": "文章1", "feed_id": "test", "url": "http://x/1"},
        ]
        rss_db.insert_items(items, "2026-01-01T12:00:00")

        # 再次插入相同 URL 应被忽略
        inserted = rss_db.insert_items(items, "2026-01-01T13:00:00")
        assert inserted == 0

    def test_mixed_insert_and_ignore(self, rss_db):
        rss_db.add_feed("测试源", "http://example.com/feed.xml")
        rss_db.insert_items(
            [{"title": "旧文", "feed_id": "test", "url": "http://x/old"}],
            "2026-01-01T12:00:00",
        )

        items = [
            {"title": "旧文", "feed_id": "test", "url": "http://x/old"},  # 重复
            {"title": "新文", "feed_id": "test", "url": "http://x/new"},  # 新增
        ]
        inserted = rss_db.insert_items(items, "2026-01-01T13:00:00")
        assert inserted == 1


class TestRSSFeedCRUD:
    def test_add_feed(self, rss_db):
        feed_id = rss_db.add_feed("36氪", "http://36kr.com/feed")
        feed = rss_db.get_feed(feed_id)
        assert feed["name"] == "36氪"
        assert feed["url"] == "http://36kr.com/feed"

    def test_update_feed(self, rss_db):
        feed_id = rss_db.add_feed("测试", "http://x.com/feed")
        rss_db.update_feed(feed_id, name="新名称")
        feed = rss_db.get_feed(feed_id)
        assert feed["name"] == "新名称"

    def test_delete_feed_cascade(self, rss_db):
        feed_id = rss_db.add_feed("测试", "http://x.com/feed")
        rss_db.insert_items(
            [{"title": "T", "feed_id": feed_id, "url": "http://x/1"}],
            "2026-01-01T12:00:00",
        )
        rss_db.delete_feed(feed_id)
        assert rss_db.get_feed(feed_id) is None
        items = rss_db.get_items(feed_id=feed_id)
        assert len(items["items"]) == 0


from datetime import datetime
class TestRSSKeywordSearch:
    def test_keyword_filter_title(self, rss_db):
        rss_db.add_feed("测试源", "http://example.com/feed.xml")
        rss_db.insert_items([
            {"title": "大模型技术突破", "feed_id": "test", "url": "http://x/1"},
            {"title": "新能源车销量", "feed_id": "test", "url": "http://x/2"},
        ], datetime.now().isoformat())

        result = rss_db.get_items(keyword="大模型")
        assert result["total"] == 1
        assert "大模型" in result["items"][0]["title"]

    def test_keyword_filter_summary(self, rss_db):
        rss_db.add_feed("测试源", "http://example.com/feed.xml")
        rss_db.insert_items([
            {"title": "新闻A", "feed_id": "test", "url": "http://x/1", "summary": "关于人工智能的报道"},
        ], datetime.now().isoformat())

        result = rss_db.get_items(keyword="人工智能")
        assert result["total"] == 1

    def test_keyword_no_match(self, rss_db):
        rss_db.add_feed("测试源", "http://example.com/feed.xml")
        rss_db.insert_items([
            {"title": "新闻A", "feed_id": "test", "url": "http://x/1"},
        ], datetime.now().isoformat())

        result = rss_db.get_items(keyword="完全不匹配的关键词")
        assert result["total"] == 0

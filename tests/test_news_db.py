"""NewsDB 核心测试：insert_many、分类过滤、向量流水线覆盖"""

import json


def _make_item(title, content="test content unique", source="test", url="http://x"):
    return {"title": title, "content": content, "source_name": source, "url": url}


class TestNewsInsertMany:
    """测试 insert_many 的去重和返回值"""

    def test_insert_new_items(self, news_db):
        items = [_make_item("标题1", "content alpha"), _make_item("标题2", "content beta")]
        added, ids = news_db.insert_many(items)
        assert added == 2
        assert len(ids) == 2
        assert all(isinstance(i, int) for i in ids)

    def test_dedup_same_title(self, news_db):
        """相同标题应去重，不重复插入"""
        items = [_make_item("相同标题")]
        news_db.insert_many(items)

        added2, ids2 = news_db.insert_many([_make_item("相同标题")])
        assert added2 == 0
        assert len(ids2) == 1  # 应返回已存在记录的 ID

    def test_update_longer_content(self, news_db):
        """新内容更长时应更新已有记录（标题 >= 4 字符时用标题去重）"""
        news_db.insert_many([_make_item("科技新闻报道", "短")])

        added, ids = news_db.insert_many([_make_item("科技新闻报道", "这是一段更长的新内容")])
        assert added == 0
        assert len(ids) == 1

        all_news = news_db.get_all()
        assert len(all_news) == 1
        assert "更长" in all_news[0]["content"]

    def test_returns_all_affected_ids(self, news_db):
        """insert_many 应返回所有受影响的 ID（包括已存在的）"""
        news_db.insert_many([_make_item("A", "ca"), _make_item("B", "cb")])

        # A 已存在，C 是新的
        added, ids = news_db.insert_many([
            _make_item("A", "ca"),  # 重复
            _make_item("C", "cc"),  # 新增
        ])
        assert added == 1
        assert len(ids) == 2  # A 的 ID + C 的 ID


class TestNewsCategoryFilter:
    """测试分类过滤逻辑"""

    def test_category_or_logic(self, news_db):
        """多分类筛选应为 OR 逻辑"""
        items = [
            _make_item("科技新闻"),
            _make_item("财经新闻"),
            _make_item("体育新闻"),
        ]
        categories = [["科技"], ["财经"], ["体育"]]
        news_db.insert_many(items, categories=categories)

        # 选择科技+财经，应返回 2 条
        result = news_db.get_all(categories=["科技", "财经"])
        assert len(result) == 2

    def test_single_category(self, news_db):
        items = [_make_item("A"), _make_item("B")]
        news_db.insert_many(items, categories=[["科技"], ["财经"]])

        result = news_db.get_all(categories=["科技"])
        assert len(result) == 1


class TestNewsCategoryStats:
    def test_category_stats(self, news_db):
        items = [
            _make_item("科技AI新闻", "c1"),
            _make_item("财经市场分析", "c2"),
            _make_item("科技产业报道", "c3"),
        ]
        news_db.insert_many(items, categories=[["科技", "AI"], ["财经"], ["科技"]])

        stats = news_db.get_category_stats()
        cat_map = {s["category"]: s["count"] for s in stats}
        assert cat_map.get("科技") == 2
        assert cat_map.get("AI") == 1
        assert cat_map.get("财经") == 1

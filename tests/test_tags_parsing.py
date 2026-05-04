"""测试 vector.py tags/category JSON 解析兜底

覆盖:
- 正常 JSON 数组
- 脏数据（非 JSON、截断 JSON、非 list）
- None / 空字符串 / 数字
- 边界值
"""

import json
import sqlite3
import os
import tempfile

import pytest


# ── _safe_parse_tags 模拟 vector.py 中 semantic_search 的 tags 解析逻辑 ──

def safe_parse_tags(raw_tags):
    """与 modules/news/vector.py semantic_search 中 tags 解析一致的逻辑"""
    try:
        tags = json.loads(raw_tags)
        if not isinstance(tags, list):
            tags = [str(tags)]
    except (json.JSONDecodeError, TypeError, ValueError):
        tags = [raw_tags] if raw_tags else []
    return tags


def safe_parse_category(raw_cat):
    """与 modules/news/vector.py backfill_existing 中 category 解析一致的逻辑"""
    if raw_cat and raw_cat.startswith("["):
        try:
            cat = json.loads(raw_cat)
            if not isinstance(cat, list):
                cat = [str(cat)]
        except (json.JSONDecodeError, TypeError):
            cat = [raw_cat]
    elif raw_cat and raw_cat != "其他":
        cat = [raw_cat]
    else:
        cat = None  # 需要分类器兜底
    return cat


class TestTagsParsing:
    """tags 字段解析测试 — 模拟 vector.py semantic_search 行为"""

    @pytest.mark.parametrize("raw, expected", [
        ('["AI", "科技"]', ["AI", "科技"]),
        ('[]', []),
        ('["单一"]', ["单一"]),
    ])
    def test_valid_json_list(self, raw, expected):
        assert safe_parse_tags(raw) == expected

    @pytest.mark.parametrize("raw, expected", [
        ('"hello"', ["hello"]),       # JSON string → wrap in list
        ('42', ["42"]),               # JSON number → wrap in list
        ('true', ["True"]),           # JSON bool → wrap in list
    ])
    def test_valid_json_non_list(self, raw, expected):
        result = safe_parse_tags(raw)
        assert isinstance(result, list)
        assert result == expected

    @pytest.mark.parametrize("raw", [
        'not json at all',
        '[broken json',
        '{invalid',
        '',
    ])
    def test_invalid_json_fallback(self, raw):
        result = safe_parse_tags(raw)
        assert isinstance(result, list)
        if raw:
            assert result == [raw]
        else:
            assert result == []

    def test_none_input(self):
        result = safe_parse_tags(None)
        assert result == []

    def test_number_input(self):
        result = safe_parse_tags(123)
        assert isinstance(result, list)


class TestCategoryParsing:
    """category 字段解析测试 — 模拟 vector.py backfill_existing 行为"""

    def test_valid_json_array(self):
        assert safe_parse_category('["科技AI", "股市"]') == ["科技AI", "股市"]

    def test_single_json_string(self):
        # 非数组开头，当作原始字符串包裹
        assert safe_parse_category('"体育"') == ['"体育"']

    def test_broken_json_array(self):
        result = safe_parse_category('["broken json')
        assert isinstance(result, list)
        assert result[0] == '["broken json'

    def test_plain_string(self):
        assert safe_parse_category("宏观经济") == ["宏观经济"]

    def test_default_category(self):
        assert safe_parse_category("其他") is None  # triggers classify fallback

    def test_empty_string(self):
        assert safe_parse_category("") is None

    def test_none(self):
        assert safe_parse_category(None) is None

    def test_nested_json_not_list(self):
        """JSON 解析结果不是 list 时 wrap"""
        result = safe_parse_category('{"key": "val"}')
        assert isinstance(result, list)
        assert len(result) == 1


class TestTagsInDatabase:
    """端到端：写入脏 tags → 读取 → 安全解析"""

    def test_read_corrupt_tags_from_db(self, tmp_db_dir):
        """直接写入非法 tags 数据，验证解析不崩溃"""
        from modules.news.db import NewsDB
        db_path = os.path.join(tmp_db_dir, "news.db")
        db = NewsDB(db_path)

        # 正常写入
        added, ids = db.insert_many([{
            "title": "正常新闻",
            "content": "内容",
            "source_name": "test",
        }])
        assert added == 1
        row_id = ids[0]

        # 直接 SQL 注入脏 tags
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE news SET tags = ? WHERE id = ?", ("NOT VALID JSON{{", row_id))
        conn.execute("UPDATE news SET tags = ? WHERE id = ?", ("", row_id + 1 if row_id + 1 else row_id))
        conn.commit()
        conn.close()

        # 读取并安全解析
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT tags FROM news WHERE id = ?", (row_id,)).fetchone()
        conn.close()

        result = safe_parse_tags(row["tags"])
        assert isinstance(result, list)

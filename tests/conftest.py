"""公共测试 fixture：临时数据库路径"""

import os
import tempfile
import pytest


@pytest.fixture
def tmp_db_dir():
    """提供临时目录用于测试数据库，测试结束自动清理"""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def news_db(tmp_db_dir):
    from modules.news.db import NewsDB
    return NewsDB(os.path.join(tmp_db_dir, "news.db"))


@pytest.fixture
def hotlist_db(tmp_db_dir):
    from modules.hotlist.db import HotlistDB
    return HotlistDB(os.path.join(tmp_db_dir, "hotlist.db"))


@pytest.fixture
def rss_db(tmp_db_dir):
    from modules.rss.db import RSSDB
    return RSSDB(os.path.join(tmp_db_dir, "rss.db"))


@pytest.fixture
def creator_db(tmp_db_dir):
    from modules.creator.db import CreatorDB
    return CreatorDB(os.path.join(tmp_db_dir, "creator.db"))

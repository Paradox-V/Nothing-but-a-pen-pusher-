"""ChatDB 单元测试"""
import pytest
from modules.chat.db import ChatDB


@pytest.fixture
def chat_db(tmp_path):
    db_path = str(tmp_path / "chat_test.db")
    return ChatDB(db_path)


def test_create_and_get_session(chat_db):
    session = chat_db.create_session("s1", "Test Session")
    assert session["id"] == "s1"
    assert session["title"] == "Test Session"
    got = chat_db.get_session("s1")
    assert got is not None
    assert got["title"] == "Test Session"


def test_delete_session_cascades_messages(chat_db):
    chat_db.create_session("s1")
    chat_db.save_message("s1", "user", "Hello")
    chat_db.save_message("s1", "assistant", "Hi there")
    assert len(chat_db.get_messages("s1")) == 2
    chat_db.delete_session("s1")
    assert chat_db.get_session("s1") is None
    assert len(chat_db.get_messages("s1")) == 0


def test_get_recent_messages_returns_latest(chat_db):
    """插入 30 条消息，get_recent_messages(limit=20) 应返回最后 20 条"""
    chat_db.create_session("s1")
    for i in range(30):
        chat_db.save_message("s1", "user", f"Message {i}")

    recent = chat_db.get_recent_messages("s1", limit=20)
    assert len(recent) == 20
    # 应该是消息 10-29（最新的 20 条），按时间正序排列
    assert recent[0]["content"] == "Message 10"
    assert recent[-1]["content"] == "Message 29"


def test_get_recent_messages_preserves_order(chat_db):
    """返回的消息应按时间正序排列（最早→最新）"""
    chat_db.create_session("s1")
    chat_db.save_message("s1", "user", "First")
    chat_db.save_message("s1", "assistant", "Second")
    chat_db.save_message("s1", "user", "Third")

    msgs = chat_db.get_recent_messages("s1", limit=3)
    assert [m["content"] for m in msgs] == ["First", "Second", "Third"]


def test_update_session_title_if_empty(chat_db):
    chat_db.create_session("s1", "")
    chat_db.update_session_title_if_empty("s1", "New Title")
    assert chat_db.get_session("s1")["title"] == "New Title"
    # 再次更新不应覆盖
    chat_db.update_session_title_if_empty("s1", "Another Title")
    assert chat_db.get_session("s1")["title"] == "New Title"


def test_save_message_with_sources(chat_db):
    chat_db.create_session("s1")
    chat_db.save_message("s1", "assistant", "Answer", sources='[{"title":"ref"}]')
    msgs = chat_db.get_messages("s1")
    assert msgs[0]["sources"] == '[{"title":"ref"}]'

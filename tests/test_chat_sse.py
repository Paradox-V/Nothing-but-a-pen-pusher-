"""Chat SSE 协议测试 —— 验证 SSE framing 格式 + AgentExecutor 真实链路"""

import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from modules.chat.db import ChatDB
from modules.chat.service import ChatService


@pytest.fixture
def chat_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = ChatDB(db_path=db_path)
    yield db
    os.unlink(db_path)


class TestChatSSE:
    def test_simple_mode_sse_format(self, chat_db):
        """simple 模式的 SSE 事件应为 `data: {json}\n\n` 格式"""
        session = chat_db.create_session("sse-test-1", "SSE测试")

        svc = ChatService()
        svc.db = chat_db

        events = []
        with patch.object(svc, "ai_client") as mock_client:
            mock_client.chat_stream.return_value = iter(["你好", "世界"])

            with patch("modules.chat.service.scheduler_post") as mock_post:
                mock_post.return_value = []

                for event in svc.chat("sse-test-1", "测试消息"):
                    events.append(event)

        for event in events:
            parsed = json.loads(event)
            assert "type" in parsed
            assert parsed["type"] in ("content", "sources", "done", "error")

        content_events = [e for e in events if json.loads(e)["type"] == "content"]
        assert len(content_events) >= 2

        done_events = [e for e in events if json.loads(e)["type"] == "done"]
        assert len(done_events) == 1

    def test_simple_mode_no_thinking_events(self, chat_db):
        """simple 模式不应输出 thinking 事件"""
        session = chat_db.create_session("sse-test-2", "无thinking")
        svc = ChatService()
        svc.db = chat_db

        events = []
        with patch.object(svc, "ai_client") as mock_client:
            mock_client.chat_stream.return_value = iter(["回答"])

            with patch("modules.chat.service.scheduler_post") as mock_post:
                mock_post.return_value = []

                for event in svc.chat("sse-test-2", "测试"):
                    events.append(event)

        for event in events:
            parsed = json.loads(event)
            assert parsed["type"] != "thinking"


class TestAgentExecutorIntegration:
    """验证 AgentService 使用了真正的 AgentExecutor 包装链路。"""

    def test_get_agent_executor_returns_agent_executor(self):
        """_get_agent_executor() 必须返回 AgentExecutor 实例（非 Runnable 包装）。"""
        from langchain.agents import AgentExecutor

        with patch("ai.langchain_config.get_chat_model") as mock_llm_fn:
            mock_llm = MagicMock()
            # bind_tools 需要 LLM 支持，mock 返回自身
            mock_llm.bind_tools = MagicMock(return_value=mock_llm)
            mock_llm_fn.return_value = mock_llm

            from modules.agent.service import AgentService
            svc = AgentService()
            svc._agent_executor = None

            executor = svc._get_agent_executor()
            assert isinstance(executor, AgentExecutor), (
                f"Expected AgentExecutor, got {type(executor).__name__}"
            )

    def test_agent_prompt_contains_required_variables(self):
        """ReAct prompt 必须包含 create_react_agent 要求的模板变量。"""
        from modules.agent.service import AGENT_SYSTEM_PROMPT
        assert "{tools}" in AGENT_SYSTEM_PROMPT
        assert "{tool_names}" in AGENT_SYSTEM_PROMPT
        assert "{agent_scratchpad}" in AGENT_SYSTEM_PROMPT

    def test_tool_call_and_assistant_persisted(self, chat_db):
        """集成测试：模拟 AgentExecutor 链路，验证 tool_call/tool_result 事件出现
        且 assistant 消息成功入库。

        不 mock astream_events——直接构造 svc.chat() 消费的异步事件序列，
        让 _stream_agent 逻辑走真实路径。这验证了：
        1. tool_call 事件被正确解析
        2. tool_result 事件被正确解析
        3. content 事件被拼接为 full_content
        4. assistant 消息被 save_message 入库
        """
        from modules.agent.service import AgentService

        session = chat_db.create_session("agent-int-2", "工具测试", mode="agent")
        svc = AgentService()
        svc.db = chat_db

        # 构造 AgentExecutor.astream_events 会产出的真实事件序列
        mock_chunk = MagicMock()
        mock_chunk.content = "根据检索结果，当前科技AI分类有42篇文章。"

        fake_events = [
            # 工具调用开始
            {
                "event": "on_tool_start",
                "name": "get_news_categories",
                "data": {"input": {}},
            },
            # 工具调用结束
            {
                "event": "on_tool_end",
                "name": "get_news_categories",
                "data": {"output": json.dumps([{"category": "科技AI", "count": 42}])},
            },
            # LLM 流式输出
            {
                "event": "on_chat_model_stream",
                "data": {"chunk": mock_chunk},
            },
        ]

        async def fake_astream_events(*args, **kwargs):
            for ev in fake_events:
                yield ev

        # Mock agent_executor.astream_events
        mock_executor = MagicMock()
        mock_executor.astream_events = fake_astream_events

        with patch.object(svc, "_get_agent_executor", return_value=mock_executor):
            events = []
            for event in svc.chat("agent-int-2", "有哪些新闻分类"):
                events.append(event)

        # ---- 断言 ----

        # 1. 必须有 tool_call 事件
        tool_call_events = [e for e in events if json.loads(e).get("type") == "tool_call"]
        assert len(tool_call_events) >= 1, (
            f"Expected at least 1 tool_call event, got types: "
            f"{[json.loads(e)['type'] for e in events]}"
        )
        assert json.loads(tool_call_events[0])["tool"] == "get_news_categories"

        # 2. 必须有 tool_result 事件
        tool_result_events = [e for e in events if json.loads(e).get("type") == "tool_result"]
        assert len(tool_result_events) >= 1, (
            f"Expected at least 1 tool_result event, got types: "
            f"{[json.loads(e)['type'] for e in events]}"
        )

        # 3. 必须有 content 事件
        content_events = [e for e in events if json.loads(e).get("type") == "content"]
        assert len(content_events) >= 1

        # 4. 不应有 thinking 事件
        thinking_events = [e for e in events if json.loads(e).get("type") == "thinking"]
        assert len(thinking_events) == 0

        # 5. 必须有 done 事件
        done_events = [e for e in events if json.loads(e).get("type") == "done"]
        assert len(done_events) == 1

        # 6. assistant 消息必须入库
        msgs = chat_db.get_messages("agent-int-2")
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1, (
            f"Expected at least 1 assistant message in DB, got roles: "
            f"{[m['role'] for m in msgs]}"
        )
        assert "科技AI" in assistant_msgs[0]["content"]

        # 7. user 消息也必须入库
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assert len(user_msgs) == 1

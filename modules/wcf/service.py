"""Agent 模式问答服务 —— ReAct Agent via langgraph + 工具调用 + 持久化"""

import asyncio
import json
import logging
from typing import Generator

from modules.agent.tools import get_all_tools

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """你是"信源汇总"平台的智能分析助手。你可以使用多种工具来检索信息，然后基于检索结果回答用户问题。

规则：
- 先思考需要哪些信息，再选择合适的工具检索
- 优先使用内部信源工具（search_news_semantic、search_multi_source、search_rss_by_topic 等）
- 如果内部信源返回无结果或结果不足，再使用 web_search 进行网络搜索
- 如果第一次检索结果不够，可以换关键词或换工具再次检索
- 只基于工具检索到的资料回答，不要编造信息
- 引用资料时标注来源（如 [新浪快讯]、[微博热榜]、[网页搜索]）
- 如果检索结果不足以回答，明确告知用户
- 回答使用中文，简洁专业，重点突出"""


class AgentService:
    """Agent 模式问答服务，持久化语义与 ChatService 对齐。"""

    def __init__(self):
        from modules.chat.db import ChatDB
        self.db = ChatDB()
        self._agent_executor = None

    def _get_agent_executor(self):
        """延迟创建 langgraph ReAct Agent。"""
        if self._agent_executor is not None:
            return self._agent_executor

        from ai.langchain_config import get_chat_model
        from langgraph.prebuilt import create_react_agent

        llm = get_chat_model(temperature=0.7, max_tokens=2000)
        tools = get_all_tools()

        self._agent_executor = create_react_agent(
            model=llm,
            tools=tools,
            prompt=AGENT_SYSTEM_PROMPT,
        )
        return self._agent_executor

    def chat(self, session_id: str, question: str,
             context: dict | None = None) -> Generator[str, None, None]:
        """Agent 模式对话，持久化语义与 ChatService.chat() 对齐。

        Args:
            session_id: 会话 ID
            question: 用户消息
            context: 可选上下文（binding_id, account_id, user_id, context_token 等），
                     由微信服务传入，注入 Agent 工具调用链
        """
        from modules.agent.tools import set_agent_context
        if context:
            set_agent_context(context)

        # 1. 自动设置会话标题
        self.db.update_session_title_if_empty(session_id, question[:20])

        # 2. 加载对话历史（先于 save_message，与 ChatService 第 71 行一致）
        history = self.db.get_recent_messages(session_id, limit=10)

        # 3. 保存用户消息（后于历史加载，与 ChatService 第 77 行一致）
        self.db.save_message(session_id, "user", question)

        # 4. 构建 agent 输入并流式执行
        agent_executor = self._get_agent_executor()
        full_content = ""
        sources_json = ""
        collected_sources = []

        # history 不含当前 question（与 ChatService._build_messages 第 133 行一致）
        messages = self._build_messages(question, history)

        try:
            import queue
            import threading
            from contextvars import copy_context

            q: queue.Queue = queue.Queue()
            _SENTINEL = object()

            async def _run():
                try:
                    async for event in agent_executor.astream_events(
                        {"messages": messages}, version="v2"
                    ):
                        q.put(event)
                except Exception as exc:
                    q.put(exc)
                finally:
                    q.put(_SENTINEL)

            # Capture current context (including _agent_context ContextVar)
            # so tools inside the thread can access it
            _ctx = copy_context()

            def _thread_target():
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(_run())
                finally:
                    loop.close()

            t = threading.Thread(target=_ctx.run, args=(_thread_target,), daemon=True)
            t.start()

            while True:
                item = q.get()
                if item is _SENTINEL:
                    break
                if isinstance(item, Exception):
                    raise item

                event = item
                event_type = event.get("event", "")

                if event_type == "on_tool_start":
                    tool_name = event.get("name", "")
                    tool_input = event.get("data", {}).get("input", {})
                    yield json.dumps({
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": tool_input if isinstance(tool_input, dict) else {},
                    }, ensure_ascii=False)

                elif event_type == "on_tool_end":
                    tool_name = event.get("name", "")
                    output = str(event.get("data", {}).get("output", ""))
                    summary = self._summarize_tool_result(tool_name, output)
                    self._collect_sources(output, collected_sources)
                    yield json.dumps({
                        "type": "tool_result",
                        "tool": tool_name,
                        "summary": summary,
                    }, ensure_ascii=False)

                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        full_content += chunk.content
                        yield json.dumps({
                            "type": "content",
                            "text": chunk.content,
                        }, ensure_ascii=False)

        except Exception as e:
            logger.error("Agent 执行失败: %s", e)
            error_msg = full_content or f"Agent 执行出错: {e}"
            yield json.dumps({"type": "error", "text": error_msg}, ensure_ascii=False)
            if full_content:
                self.db.save_message(session_id, "assistant", full_content, sources="")
            return

        # 5. 保存 assistant 消息 + sources
        if collected_sources:
            sources_json = json.dumps(collected_sources, ensure_ascii=False)
        if full_content:
            self.db.save_message(session_id, "assistant", full_content, sources=sources_json)

        # 6. yield sources + done
        if sources_json:
            yield json.dumps({"type": "sources", "data": sources_json}, ensure_ascii=False)
        yield json.dumps({"type": "done"})

    def _build_messages(self, question: str, history: list[dict]) -> list[dict]:
        """构建 langgraph 消息列表。

        chat_history 不含当前 question，question 作为最后一条 HumanMessage。
        """
        messages = []
        for msg in history:
            role = msg.get("role", "")
            if role == "user":
                messages.append({"role": "user", "content": msg["content"]})
            elif role == "assistant":
                messages.append({"role": "assistant", "content": msg["content"]})
        messages.append({"role": "user", "content": question})
        return messages

    def _summarize_tool_result(self, tool_name: str, output: str) -> str:
        """为前端生成工具结果摘要。"""
        try:
            data = json.loads(output)
            if isinstance(data, list):
                return f"找到 {len(data)} 条结果"
            if isinstance(data, dict):
                if "error" in data:
                    return data["error"]
                if "items" in data:
                    return f"找到 {len(data['items'])} 条结果"
                if "total" in data:
                    return f"共 {data.get('total', '?')} 条"
            return "完成"
        except (json.JSONDecodeError, TypeError):
            return "完成"

    def _collect_sources(self, output: str, sources: list):
        """从工具结果中提取来源信息。"""
        try:
            data = json.loads(output)
            items = data if isinstance(data, list) else data.get("items", [])
            for item in items[:5]:
                if isinstance(item, dict) and item.get("title"):
                    sources.append({
                        "title": item.get("title", ""),
                        "source": item.get("source_name", item.get("platform_name", "")),
                        "url": item.get("url", ""),
                        "source_type": item.get("source_type", ""),
                    })
        except (json.JSONDecodeError, TypeError):
            pass


# WCF 模块别名 —— scheduler 和其他模块通过 WCFService 引用
WCFService = AgentService

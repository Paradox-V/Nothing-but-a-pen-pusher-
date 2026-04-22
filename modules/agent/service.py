"""Agent 模式问答服务 —— ReAct Agent + AgentExecutor + 工具调用 + 持久化"""

import asyncio
import json
import logging
from typing import Generator

from modules.agent.tools import get_all_tools

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """你是"信源汇总"平台的智能分析助手。你可以使用多种工具来检索信息，然后基于检索结果回答用户问题。

规则：
- 先思考需要哪些信息，再选择合适的工具检索
- 如果第一次检索结果不够，可以换关键词或换工具再次检索
- 只基于工具检索到的资料回答，不要编造信息
- 引用资料时标注来源（如 [新浪快讯]、[微博热榜]）
- 如果检索结果不足以回答，明确告知用户
- 回答使用中文，简洁专业，重点突出

你可以使用以下工具：
{tools}

工具名称列表: {tool_names}

使用工具时，请严格按照以下格式：
Question: 用户的问题
Thought: 你对问题的思考
Action: 要使用的工具名称（必须是上面列表中的一个）
Action Input: 工具的输入参数（JSON格式）
Observation: 工具的返回结果
...（可以重复 Thought/Action/Action Input/Observation 多次）
Thought: 我现在有了足够的信息来回答问题
Final Answer: 最终回答

对话历史：
{chat_history}

开始！

Question: {input}
Thought: {agent_scratchpad}"""


class AgentService:
    """Agent 模式问答服务，持久化语义与 ChatService 对齐。"""

    def __init__(self):
        from modules.chat.db import ChatDB
        self.db = ChatDB()
        self._agent_executor = None

    def _get_agent_executor(self):
        """延迟创建 AgentExecutor（create_react_agent + AgentExecutor 包装）。"""
        if self._agent_executor is not None:
            return self._agent_executor

        from ai.langchain_config import get_chat_model
        from langchain.agents import AgentExecutor, create_react_agent
        from langchain_core.prompts import PromptTemplate

        llm = get_chat_model(temperature=0.7, max_tokens=2000)
        tools = get_all_tools()

        prompt = PromptTemplate.from_template(AGENT_SYSTEM_PROMPT)

        agent = create_react_agent(llm, tools, prompt)
        self._agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=False,
            max_iterations=8,
            handle_parsing_errors=True,
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
        agent_input = self._build_agent_input(question, history)

        try:
            import queue
            import threading

            q: queue.Queue = queue.Queue()
            _SENTINEL = object()

            async def _run():
                try:
                    async for event in agent_executor.astream_events(
                        agent_input, version="v1"
                    ):
                        q.put(event)
                except Exception as exc:
                    q.put(exc)
                finally:
                    q.put(_SENTINEL)

            def _thread_target():
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(_run())
                finally:
                    loop.close()

            t = threading.Thread(target=_thread_target, daemon=True)
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

    def _build_agent_input(self, question: str, history: list[dict]) -> dict:
        """构建 AgentExecutor 输入。

        chat_history 不含当前 question（与 ChatService._build_messages 第 133 行一致），
        question 作为 input 单独传入。
        """
        chat_history = ""
        for msg in history:
            role = msg.get("role", "")
            if role in ("user", "assistant"):
                chat_history += f"{role}: {msg['content']}\n"

        return {
            "input": question,
            "chat_history": chat_history.strip(),
        }

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

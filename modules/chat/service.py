"""
QA 核心服务 —— 代理向量检索 + DeepSeek 流式生成

运行于 Flask 进程中，不加载嵌入模型。
所有向量操作通过调度器 5001 端口代理。
"""

import json
import logging
import os
from typing import Generator

import httpx

from utils.scheduler_client import scheduler_post

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是"信源汇总"平台的智能分析助手。根据以下检索到的新闻、热榜、RSS 资料回答用户问题。

规则：
- 只基于检索到的资料回答，不要编造信息
- 引用资料时标注来源（如 [新浪快讯]、[微博热榜]）
- 如果检索结果不足以回答，明确告知用户
- 回答使用中文
- 回答要简洁专业，重点突出"""


class ChatService:
    """对话式 QA 服务"""

    def __init__(self):
        from modules.chat.db import ChatDB
        self.db = ChatDB()
        self.ai_config = self._build_ai_config()
        self._ai_client = None

    @property
    def ai_client(self):
        """延迟初始化 AI 客户端（避免启动时无 API key 报错）"""
        if self._ai_client is None:
            from ai.client import AIClient
            self._ai_client = AIClient(self.ai_config)
        return self._ai_client

    def _build_ai_config(self) -> dict:
        from ai.config import get_ai_config
        config = get_ai_config()
        config["TEMPERATURE"] = 0.7
        config["MAX_TOKENS"] = 2000
        return config

    def chat(self, session_id: str, question: str) -> Generator[str, None, None]:
        """核心对话流程：检索 → 构建 Prompt → 流式生成。"""
        # 1. 代理到调度器进行向量检索
        search_results = []
        try:
            result = scheduler_post("/chat_search", json_data={"query": question, "top_k": 5}, timeout=10)
            if result and isinstance(result, list):
                search_results = result
        except Exception as e:
            logger.warning("向量检索失败: %s", e)

        # 2. 更新会话标题（首条消息时）
        self.db.update_session_title_if_empty(session_id, question[:20])

        # 3. 格式化检索上下文
        context = self._format_context(search_results)

        # 4. 加载对话历史（最近 20 条消息）
        history = self.db.get_recent_messages(session_id, limit=20)

        # 5. 构建消息列表
        messages = self._build_messages(history, question, context)

        # 6. 保存用户消息
        self.db.save_message(session_id, "user", question)

        # 7. 流式调用 DeepSeek
        full_response = []
        try:
            for chunk in self.ai_client.chat_stream(messages):
                full_response.append(chunk)
                yield json.dumps({"type": "content", "text": chunk}, ensure_ascii=False)
        except Exception as e:
            error_msg = ''.join(full_response) if full_response else f"生成回答时出错: {e}"
            yield json.dumps({"type": "error", "text": error_msg}, ensure_ascii=False)
            if full_response:
                self.db.save_message(session_id, "assistant", error_msg)
            return

        # 8. 保存助手回复和引用来源
        sources_json = json.dumps(
            [{"title": r.get("title", ""),
              "source": r.get("source_name", r.get("platform_name", "")),
              "url": r.get("url", ""),
              "source_type": r.get("source_type", "")}
             for r in search_results],
            ensure_ascii=False,
        )
        self.db.save_message(session_id, "assistant", "".join(full_response), sources_json)
        yield json.dumps({"type": "sources", "data": sources_json}, ensure_ascii=False)
        yield json.dumps({"type": "done"})

    def _format_context(self, results: list[dict]) -> str:
        """将检索结果格式化为 LLM 上下文。"""
        if not results:
            return "（未检索到相关资料）"

        parts = []
        for i, r in enumerate(results, 1):
            source = r.get("source_name", r.get("platform_name", "未知来源"))
            title = r.get("title", "")
            content = r.get("content", "")
            # 新闻有完整 content，热榜/RSS 只有 title
            if content and content != title:
                text = f"[{i}] [{source}] {title}\n{content[:300]}"
            else:
                text = f"[{i}] [{source}] {title}"
            parts.append(text)

        return "\n\n".join(parts)

    def _build_messages(self, history: list[dict], question: str, context: str) -> list[dict]:
        """构建发送给 LLM 的消息列表。"""
        messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n参考资料：\n{context}"}]

        for msg in history:
            role = msg["role"]
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": msg["content"]})

        messages.append({"role": "user", "content": question})
        return messages

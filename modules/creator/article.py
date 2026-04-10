"""
文案创作模块 - 文章生成

根据确认的框架生成完整文章
"""

import json
import logging
import threading
import uuid
from typing import Any

from modules.creator.framework import (
    Framework,
    FrameworkStatus,
    get_framework,
    store_framework,
    _call_llm,
    _default_ai_config,
)
from modules.creator.db import CreatorDB

logger = logging.getLogger(__name__)

# 持久化任务存储
_db = CreatorDB()


def start_article_generation(
    fw_id: str,
    image_count: int = 0,
    ai_config: dict | None = None,
) -> str:
    """
    启动异步文章生成任务。返回 task_id。
    """
    fw = get_framework(fw_id)
    if not fw:
        raise ValueError(f"框架 {fw_id} 不存在")
    if fw.status != FrameworkStatus.CONFIRMED:
        raise ValueError("框架未确认，无法生成文章")

    task_id = uuid.uuid4().hex[:12]
    _db.create_task(task_id, fw_id)

    config = ai_config or _default_ai_config()

    def _worker():
        try:
            _db.update_task(task_id, progress="正在生成文章...")
            article = _generate_article(fw, config)
            fw.final_article = article
            fw.status = FrameworkStatus.COMPLETED

            # 配图
            images = []
            if image_count > 0:
                _db.update_task(task_id, progress=f"正在生成 {image_count} 张配图...")
                from modules.creator.image_gen import generate_images
                images = generate_images(article, image_count)

            fw.images = images
            store_framework(fw)

            _db.update_task(
                task_id,
                status="completed",
                progress="完成",
                result={
                    "article": article,
                    "images": images,
                    "framework_id": fw_id,
                },
            )

        except Exception as e:
            logger.error("文章生成任务失败: %s", e)
            _db.update_task(task_id, status="failed", progress=str(e))
            fw.status = FrameworkStatus.FAILED
            store_framework(fw)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return task_id


def get_task_status(task_id: str) -> dict | None:
    return _db.get_task(task_id)


def _generate_article(fw: Framework, ai_config: dict) -> str:
    """调用 LLM 根据框架生成完整文章"""

    framework_desc = f"""行业: {fw.industry}
关键词: {fw.keyword}
文章结构: {fw.article_structure}
切入点+创作维度+核心观点: {fw.writing_approach}"""

    prompt = f"""你是一个专业的文章撰写者，需要根据已确认的内容框架生成完整的文章。

【文章标题】
{fw.title}

【写作要求】
{fw.requirements or "无特殊要求"}

【内容框架】
{framework_desc}

【参考素材】
{fw.reference_material[:800] or "无参考素材"}

【生成要求】
1. 必须使用标题"{fw.title}"作为正文题目，使用Markdown格式：# {fw.title}，且必须作为文章的第一行
2. 严格按照框架中的结构撰写
3. 确保文章逻辑连贯，内容充实
4. 语言流畅，符合公众号文章风格
5. 文章总字数 1500-3000 字
6. 直接输出文章内容，不要添加任何引言或开场白
7. 使用 Markdown 格式，适当使用二级标题分段

请立即开始生成文章："""

    messages = [
        {"role": "system", "content": "你是一个专业的文章撰写者，能够根据内容框架生成高质量的文章。"},
        {"role": "user", "content": prompt},
    ]

    article = _call_llm(messages, ai_config)

    # 确保标题格式
    if f"# {fw.title}" not in article:
        article = f"# {fw.title}\n\n{article}"

    return article

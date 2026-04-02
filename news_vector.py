"""
语义向量引擎 —— Embedding 去重 + 分类 + 聚类 + 语义搜索

基于 BAAI/bge-small-zh-v1.5 模型 + ChromaDB 实现。
"""

import hashlib
import json
import logging
import sqlite3
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# ── 关键词规则分类（优先匹配，命中即归入对应分类） ──────────

KEYWORD_RULES: dict[str, list[str]] = {
    "体育": [
        "比赛", "冠军", "联赛", "世界杯", "奥运", "足球", "篮球", "NBA", "CBA",
        "网球", "乒乓球", "羽毛球", "排球", "田径", "游泳", "拳击", "F1", "斯诺克",
        "高尔夫", "运动员", "教练", "决赛", "半决赛", "决赛圈", "进球", "得分",
        "赛季", "赛程", "夺冠", "金牌", "银牌", "铜牌", "全运会", "亚运会",
    ],
    "时事": [
        "社会", "事故", "灾害", "地震", "洪水", "台风", "暴雨", "天气", "气象",
        "高考", "就业", "人口", "养老", "教育", "医疗", "交通", "食品安全",
        "环保", "调查", "通报", "发布会", "外交", "会谈", "访问", "峰会",
        "救援", "遇难", "伤亡", "失踪", "疫情", "防控", "应急",
    ],
    "国内": [
        "中国", "国内", "全国", "各省", "国务院", "发改委", "商务部", "工信部",
        "财政部", "住建部", "央行", "证监会", "银保监", "乡村振兴",
        "粤港澳", "京津冀", "长三角", "一带一路", "人大代表", "政协",
        "人大常委会", "最高法", "最高检", "国务院办公厅",
    ],
}

# ── 分类原型文本（Embedding 相似度分类） ──────────────────────

CATEGORY_PROTOTYPES: dict[str, list[str]] = {
    "宏观经济": [
        "国家统计局发布GDP数据，经济增速放缓或回升",
        "央行宣布降息或加息，调整LPR利率和存款准备金率",
        "CPI通胀数据公布，PMI制造业采购经理指数变化",
        "社融规模和M2货币供应量同比增长，逆回购操作",
        "货币政策调整，经济数据发布，财政政策变化",
    ],
    "股市": [
        "A股三大指数集体上涨或下跌，沪指深成指创业板走势",
        "北向资金大幅净流入或流出，成交额突破万亿",
        "上市公司发布减持或增持公告，股东变动",
        "科创板新股申购注册制改革，退市制度执行",
        "融资融券余额变化，涨停跌停股票数量，大盘行情",
    ],
    "期货商品": [
        "原油期货价格大幅波动，国际油价走势分析",
        "黄金期货价格创新高，避险需求上升",
        "有色金属铜铝镍价格变动，大宗商品市场走势",
        "铁矿石螺纹钢期货价格波动，焦煤焦炭行情",
        "碳酸锂价格走势，豆粕棕榈油白糖棉花期货",
    ],
    "外汇": [
        "美元指数走强或走弱，人民币汇率波动",
        "美联储利率决议影响外汇市场，非农数据发布",
        "离岸人民币和在岸人民币汇率差异变化",
        "欧元日元英镑兑美元汇率走势分析",
        "外汇储备规模变化，跨境资金流动",
    ],
    "债券": [
        "国债收益率曲线变动，十年期国债利率走势",
        "信用债违约事件，债券市场风险偏好变化",
        "地方债发行规模扩大，可转债市场活跃",
        "债券评级下调或上调，利差收窄或扩大",
    ],
    "科技AI": [
        "人工智能大模型发布，GPT类模型技术突破",
        "芯片半导体行业动态，GPU算力需求增长",
        "英伟达台积电发布财报，光刻机技术进展",
        "AI应用落地自动驾驶智能机器人新突破",
        "DeepSeek开源模型发布，量子计算技术前沿",
    ],
    "地缘政治": [
        "中东局势紧张，伊朗以色列冲突升级",
        "俄罗斯乌克兰战争进展，北约东扩争议",
        "美国关税政策调整，中美贸易战升级或缓和",
        "红海航运安全胡塞武装袭击商船事件",
        "国际制裁措施，军事冲突导弹试验地区紧张",
    ],
    "产业政策": [
        "新能源汽车销量增长，光伏风电装机容量扩大",
        "房地产调控政策出台，楼市成交量变化",
        "储能充电桩建设加速，碳中和碳达峰目标推进",
        "医药集采降价，教育双减政策落实情况",
        "新质生产力智能制造，消费零售文旅产业复苏",
    ],
}


# ── 向量引擎 ────────────────────────────────────────────────

class NewsVectorEngine:
    """Embedding 语义去重、分类、聚类、搜索。"""

    DEDUP_THRESHOLD = 0.78   # 语义去重阈值（适配短快讯，换几个词不会被误杀）
    CLUSTER_THRESHOLD = 0.85  # 聚类阈值
    CLASSIFY_THRESHOLD = 0.50  # Embedding 分类相似度阈值（从 0.28 提高到 0.50，减少不相关标签）
    MODEL_NAME = "BAAI/bge-small-zh-v1.5"

    def __init__(self, db_path: str = "/opt/news_viewer/news.db",
                 chroma_dir: str = "/opt/news_viewer/chroma_db"):
        self.db_path = db_path
        self.chroma_dir = chroma_dir
        self.model: SentenceTransformer | None = None
        self.chroma_client: chromadb.PersistentClient | None = None
        self.collection: chromadb.Collection | None = None
        self._initialized = False
        self._category_embeddings: dict[str, list[float]] = {}

    def initialize(self) -> None:
        """加载模型和 ChromaDB。"""
        if self._initialized:
            return

        logger.info("加载 Embedding 模型: %s ...", self.MODEL_NAME)
        self.model = SentenceTransformer(self.MODEL_NAME)
        logger.info("模型加载完成，维度: %d", self.model.get_sentence_embedding_dimension())

        self.chroma_client = chromadb.PersistentClient(path=self.chroma_dir)
        self.collection = self.chroma_client.get_or_create_collection(
            name="news_embeddings",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB 就绪，已有 %d 条向量", self.collection.count())
        self._initialized = True

        # 预计算分类原型向量
        self._init_category_embeddings()

    # ── Embedding 计算 ──────────────────────────────────────

    def _encode(self, texts: list[str]) -> list[list[float]]:
        """批量化文本编码。"""
        if not texts:
            return []
        embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.tolist()

    def _text_for_embed(self, title: str, content: str) -> str:
        """拼接标题+内容前200字用于 embedding。"""
        combined = f"{title}。{content[:200]}" if title else content[:300]
        return combined.strip()

    # ── 分类原型向量 ────────────────────────────────────────

    def _init_category_embeddings(self) -> None:
        """为每个分类的示例文本计算 embedding，取平均值作为原型向量。"""
        if not self.model:
            return
        for cat, sentences in CATEGORY_PROTOTYPES.items():
            embs = self._encode(sentences)
            # 取平均并归一化
            dim = len(embs[0])
            avg = [0.0] * dim
            for emb in embs:
                for i in range(dim):
                    avg[i] += emb[i]
            n = len(embs)
            for i in range(dim):
                avg[i] /= n
            # L2 归一化
            norm = sum(v * v for v in avg) ** 0.5
            if norm > 0:
                avg = [v / norm for v in avg]
            self._category_embeddings[cat] = avg
        logger.info("分类原型向量就绪: %d 个分类", len(self._category_embeddings))

    # ── 语义去重 ─────────────────────────────────────────────

    def semantic_dedup(self, items: list[dict]) -> list[dict]:
        """
        将新条目与 ChromaDB 已有条目做语义比较，移除语义重复（>threshold）。
        返回去重后的条目列表。
        """
        if not items or self.collection.count() == 0:
            return items

        texts = [self._text_for_embed(it["title"], it["content"]) for it in items]
        embeddings = self._encode(texts)

        kept = []
        for i, (item, emb) in enumerate(zip(items, embeddings)):
            results = self.collection.query(
                query_embeddings=[emb],
                n_results=1,
                include=["distances", "metadatas"],
            )
            if results["distances"] and results["distances"][0]:
                dist = results["distances"][0][0]
                similarity = 1 - dist  # cosine distance → similarity
                if similarity > self.DEDUP_THRESHOLD:
                    existing_title = ""
                    if results["metadatas"] and results["metadatas"][0]:
                        existing_title = results["metadatas"][0][0].get("title", "")
                    logger.info(
                        "语义去重: '%s' 与已有条目 '%s' 相似度 %.2f, 已移除",
                        item["title"][:30], existing_title[:30], similarity,
                    )
                    continue
            kept.append(item)

        removed = len(items) - len(kept)
        if removed:
            logger.info("语义去重: 移除 %d 条语义重复", removed)
        return kept

    # ── Embedding 相似度分类 ─────────────────────────────────

    def classify(self, text: str) -> str:
        """向后兼容：返回第一个匹配的 category。"""
        return self.classify_multi(text)[0]

    def classify_multi(self, text: str) -> list[str]:
        """混合分类：关键词规则优先 + Embedding 相似度补充。"""
        categories: list[str] = []

        # 第一步：关键词规则匹配
        for cat, keywords in KEYWORD_RULES.items():
            for kw in keywords:
                if kw in text:
                    categories.append(cat)
                    break

        # 第二步：Embedding 相似度补充（仅对 Embedding 原型中的分类）
        if self.model and self._initialized and self._category_embeddings:
            text_emb = self._encode([text])[0]
            for cat, cat_emb in self._category_embeddings.items():
                if cat in categories:
                    continue  # 关键词已匹配，跳过
                sim = sum(a * b for a, b in zip(text_emb, cat_emb))
                if sim > self.CLASSIFY_THRESHOLD:
                    categories.append(cat)

        if not categories:
            return ["其他"]

        # 去重保序，最多 6 个标签
        seen: set[str] = set()
        return [c for c in categories if not (c in seen or seen.add(c))][:6]

    def classify_texts(self, texts: list[str]) -> list[list[str]]:
        """批量多标签分类：关键词规则 + Embedding 相似度，一次 encode 所有文本。"""
        import numpy as np

        # 第一步：对所有文本做关键词匹配
        all_keyword_cats: list[list[str]] = []
        for text in texts:
            cats: list[str] = []
            for cat, keywords in KEYWORD_RULES.items():
                for kw in keywords:
                    if kw in text:
                        cats.append(cat)
                        break
            all_keyword_cats.append(cats)

        # 第二步：批量 encode，计算 embedding 相似度
        if self.model and self._initialized and self._category_embeddings:
            embs = self._encode(texts)  # 一次 encode 全部
            cat_names = list(self._category_embeddings.keys())
            cat_matrix = np.array([self._category_embeddings[c] for c in cat_names])  # (C, D)
            emb_matrix = np.array(embs)  # (N, D)
            sim_matrix = emb_matrix @ cat_matrix.T  # (N, C)

            for i, text in enumerate(texts):
                for j, cat in enumerate(cat_names):
                    if cat in all_keyword_cats[i]:
                        continue
                    if sim_matrix[i, j] > self.CLASSIFY_THRESHOLD:
                        all_keyword_cats[i].append(cat)

        # 第三步：兜底 + 去重保序，最多 6 个标签
        results: list[list[str]] = []
        for cats in all_keyword_cats:
            if not cats:
                results.append(["其他"])
            else:
                seen: set[str] = set()
                results.append([c for c in cats if not (c in seen or seen.add(c))][:6])
        return results

    def classify_items(self, items: list[dict]) -> list[list[str]]:
        """批量多标签分类，返回与 items 等长的 list[list[str]]。"""
        return [self.classify_multi(f"{it['title']} {it['content']}") for it in items]

    # ── 聚类分配 ─────────────────────────────────────────────

    def assign_clusters(self, items: list[dict]) -> list[str]:
        """
        增量最近邻聚类：新条目与 ChromaDB 已有向量比较。
        > threshold 归入同 cluster_id，否则生成新 cluster_id。
        返回与 items 等长的 cluster_id 列表。
        """
        if not items:
            return []

        texts = [self._text_for_embed(it["title"], it["content"]) for it in items]
        embeddings = self._encode(texts)

        cluster_ids = []
        for i, emb in enumerate(embeddings):
            assigned = False
            if self.collection.count() > 0:
                results = self.collection.query(
                    query_embeddings=[emb],
                    n_results=min(5, self.collection.count()),
                    include=["distances", "metadatas"],
                )
                if results["distances"] and results["distances"][0]:
                    for j, dist in enumerate(results["distances"][0]):
                        similarity = 1 - dist
                        if similarity > self.CLUSTER_THRESHOLD:
                            cid = results["metadatas"][0][j].get("cluster_id")
                            if cid:
                                cluster_ids.append(cid)
                                assigned = True
                                break
            if not assigned:
                # 生成新 cluster_id：基于内容哈希
                h = hashlib.md5(
                    f"{items[i]['title']}:{items[i]['content'][:50]}".encode()
                ).hexdigest()[:12]
                cluster_ids.append(f"cluster_{h}")

        return cluster_ids

    # ── 写入 ChromaDB ───────────────────────────────────────

    def upsert_to_chroma(
        self,
        items: list[dict],
        row_ids: list[int],
        categories: list[list[str]],
        cluster_ids: list[str],
    ) -> None:
        """将条目写入 ChromaDB（embedding + metadata）。categories 为 list[list[str]]。"""
        if not items:
            return

        texts = [self._text_for_embed(it["title"], it["content"]) for it in items]
        embeddings = self._encode(texts)

        ids = [str(rid) for rid in row_ids]
        metadatas = []
        for it, cat, cid in zip(items, categories, cluster_ids):
            metadatas.append({
                "source_name": it["source_name"],
                "title": it["title"][:200],
                "category": ",".join(cat) if isinstance(cat, list) else cat,
                "cluster_id": cid,
                "timestamp": it.get("timestamp") or "",
            })

        documents = texts

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )
        logger.info("ChromaDB 写入 %d 条", len(items))

    # ── 语义搜索 ─────────────────────────────────────────────

    def semantic_search(
        self,
        query: str,
        n: int = 20,
        categories: list[str] | None = None,
        sources: list[str] | None = None,
    ) -> list[dict]:
        """
        语义搜索：返回与 query 最相似的新闻条目。
        可按 categories / sources 过滤（支持多值）。
        category metadata 存为逗号分隔字符串，用 $contains 匹配。
        """
        if not self.model or not self._initialized:
            return []

        query_emb = self._encode([query])[0]

        where_filter = None
        conditions = []
        if categories:
            cat_conds = [{"category": {"$contains": cat}} for cat in categories]
            if len(cat_conds) == 1:
                conditions.append(cat_conds[0])
            else:
                conditions.append({"$or": cat_conds})
        if sources:
            src_conds = [{"source_name": src} for src in sources]
            if len(src_conds) == 1:
                conditions.append(src_conds[0])
            else:
                conditions.append({"$or": src_conds})
        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        n_results = min(n, self.collection.count()) if self.collection.count() > 0 else 0
        if n_results == 0:
            return []

        results = self.collection.query(
            query_embeddings=[query_emb],
            n_results=n_results,
            where=where_filter,
            include=["metadatas", "distances", "documents"],
        )

        output = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 0
                output.append({
                    "id": int(doc_id),
                    "title": meta.get("title", ""),
                    "source_name": meta.get("source_name", ""),
                    "category": meta.get("category", "").split(",") if meta.get("category") else [],
                    "cluster_id": meta.get("cluster_id", ""),
                    "timestamp": meta.get("timestamp", ""),
                    "similarity": round(1 - dist, 4),
                })

        # 补充完整内容：从 SQLite 读取
        if output:
            ids_to_fetch = [o["id"] for o in output]
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" * len(ids_to_fetch))
            rows = conn.execute(
                f"SELECT id, content, url, tags, created_at FROM news WHERE id IN ({placeholders})",
                ids_to_fetch,
            ).fetchall()
            row_map = {r["id"]: r for r in rows}
            conn.close()

            for o in output:
                r = row_map.get(o["id"])
                if r:
                    o["content"] = r["content"]
                    o["url"] = r["url"]
                    o["tags"] = json.loads(r["tags"])
                    o["created_at"] = r["created_at"]

        return output

    # ── 同步清理 ─────────────────────────────────────────────

    def sync_chroma_purge(self) -> int:
        """清理 ChromaDB 中已从 SQLite 删除的条目。"""
        conn = sqlite3.connect(self.db_path)
        existing_ids = {str(r[0]) for r in conn.execute("SELECT id FROM news").fetchall()}
        conn.close()

        chroma_ids = self.collection.get()["ids"]
        to_delete = [cid for cid in chroma_ids if cid not in existing_ids]

        if to_delete:
            self.collection.delete(ids=to_delete)
            logger.info("ChromaDB 清理 %d 条过期条目", len(to_delete))

        return len(to_delete)

    # ── 回填已有数据 ─────────────────────────────────────────

    def backfill_existing(self) -> int:
        """首次部署时，将 SQLite 已有数据回填到 ChromaDB。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, source_name, title, content, timestamp, url, tags, "
            "COALESCE(category, '其他') as category, cluster_id "
            "FROM news ORDER BY id"
        ).fetchall()
        conn.close()

        if not rows:
            logger.info("回填: SQLite 无数据")
            return 0

        # 过滤掉已在 ChromaDB 中的条目
        existing_ids = set(self.collection.get()["ids"])
        new_rows = [r for r in rows if str(r["id"]) not in existing_ids]

        if not new_rows:
            logger.info("回填: 所有条目已存在 ChromaDB 中")
            return 0

        logger.info("回填: 需要处理 %d 条", len(new_rows))

        # 批量处理，每次 100 条
        batch_size = 100
        total_done = 0

        for start in range(0, len(new_rows), batch_size):
            batch = new_rows[start:start + batch_size]

            items = []
            row_ids = []
            categories = []
            cluster_ids = []

            for r in batch:
                text = f"{r['title']} {r['content']}"
                # 支持旧数据（单值字符串）和新数据（JSON 数组）
                raw_cat = r["category"]
                if raw_cat and raw_cat.startswith("["):
                    cat = json.loads(raw_cat)
                elif raw_cat and raw_cat != "其他":
                    cat = [raw_cat]
                else:
                    cat = self.classify_multi(text)
                cid = r["cluster_id"] or ""

                items.append({
                    "source_name": r["source_name"],
                    "title": r["title"],
                    "content": r["content"],
                    "timestamp": r["timestamp"],
                })
                row_ids.append(r["id"])
                categories.append(cat)
                cluster_ids.append(cid)

            texts = [self._text_for_embed(it["title"], it["content"]) for it in items]
            embeddings = self._encode(texts)

            ids = [str(rid) for rid in row_ids]
            metadatas = []
            for it, cat, cid in zip(items, categories, cluster_ids):
                metadatas.append({
                    "source_name": it["source_name"],
                    "title": it["title"][:200],
                    "category": ",".join(cat) if isinstance(cat, list) else cat,
                    "cluster_id": cid,
                    "timestamp": it.get("timestamp") or "",
                })

            self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=texts,
            )
            total_done += len(batch)
            logger.info("回填进度: %d / %d", total_done, len(new_rows))

        logger.info("回填完成: 共处理 %d 条", total_done)
        return total_done

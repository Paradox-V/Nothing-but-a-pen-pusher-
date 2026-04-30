"""
统一调度器 - 独立进程运行（轻量版）

定时调度三个模块的数据采集：新闻、热榜、RSS
向量操作委托给 vector_service.py（端口 5001），本进程不加载模型。
"""
import json
import logging
import os
import threading
import time
from datetime import datetime

from utils.config import load_config
from utils.vector_client import VectorClient
from modules.news.db import NewsDB
from modules.news.aggregator import AKSourceAggregator
from modules.hotlist.db import HotlistDB
from modules.hotlist.fetcher import DataFetcher
from modules.rss.db import RSSDB
from modules.rss.fetcher import RSSFetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    config = load_config()
    sched_cfg = config.get("scheduler", {})
    purge_days = sched_cfg.get("purge_days", 7)

    # --- 向量服务客户端（HTTP，不加载模型） ---
    vec = VectorClient()
    vec_available = vec.is_healthy()
    if vec_available:
        logger.info("向量服务在线，将通过 HTTP 委托向量操作")
    else:
        logger.warning("向量服务离线，将以无向量模式运行（去重/分类/搜索不可用）")

    # 启动时：回填 & 迁移（委托给向量服务）
    if vec_available:
        try:
            result = vec.migrate_categories()
            migrated = result.get("migrated", 0)
            if migrated > 0:
                logger.info("数据迁移完成: %d 条", migrated)
        except Exception as e:
            logger.error("数据迁移失败: %s", e)
        try:
            result = vec.backfill()
            count = result.get("backfilled", 0)
            if count > 0:
                logger.info("回填完成: %d 条", count)
        except Exception as e:
            logger.error("回填失败: %s", e)

    # --- 代理配置 ---
    proxy_url = config.get("proxy", {}).get("url")

    # --- 新闻模块 ---
    news_db = NewsDB()
    aktools_url = config.get("aktools", {}).get("base_url")
    aggregator = AKSourceAggregator(base_url=aktools_url, db=news_db)

    # --- 热榜模块 ---
    hotlist_db = HotlistDB()
    hotlist_cfg = config.get("hotlist", {})
    hotlist_fetcher = DataFetcher(api_url=hotlist_cfg.get("api_url"), proxy_url=proxy_url)

    # --- RSS 模块 ---
    rss_db = RSSDB()
    rss_fetcher = RSSFetcher(proxy_url=proxy_url)

    # --- 归档模块（配置控制） ---
    archive_cfg = config.get("archive", {})
    archive_enabled = archive_cfg.get("enabled", False)

    # 计时器
    timers = {"news": 0, "hotlist": 0, "rss": 0}
    intervals = {
        "news": sched_cfg.get("news_interval", 600),
        "hotlist": sched_cfg.get("hotlist_interval", 300),
        "rss": sched_cfg.get("rss_interval", 1800),
    }

    logger.info(
        "调度器启动（轻量模式）: news=%ds, hotlist=%ds, rss=%ds, purge=%dd",
        intervals["news"], intervals["hotlist"], intervals["rss"], purge_days,
    )

    # 启动时立即执行一次
    for module in ["news", "hotlist", "rss"]:
        _run_module(module, news_db, aggregator, vec,
                    hotlist_db, hotlist_fetcher, hotlist_cfg,
                    rss_db, rss_fetcher, purge_days,
                    archive_enabled=archive_enabled)

    # 加载抓取触发器
    from utils.crawl_trigger import CrawlTrigger
    crawl_trigger = CrawlTrigger()

    # 心跳文件
    heartbeat_path = "data/.scheduler_heartbeat"
    os.makedirs("data", exist_ok=True)

    monitor_cfg = _get_monitor_config()
    monitor_timer = 0

    wcf_cfg = _get_wcf_config()
    wcf_timer = 0

    while True:
        time.sleep(1)

        # 心跳（每 30 秒）
        heartbeat_counter = getattr(main, '_hb_cnt', 0) + 1
        if heartbeat_counter >= 30:
            heartbeat_counter = 0
            try:
                with open(heartbeat_path, "w") as f:
                    f.write(datetime.now().isoformat())
            except Exception:
                pass
        main._hb_cnt = heartbeat_counter

        # 定期检查向量服务是否恢复
        if not vec_available:
            if heartbeat_counter == 1:
                vec_available = vec.is_healthy()
                if vec_available:
                    logger.info("向量服务已恢复上线")

        # Web 触发的抓取信号
        try:
            pending = crawl_trigger.poll_pending()
            for module in pending:
                logger.info("收到 Web 触发的抓取信号: %s", module)
                _run_module(module, news_db, aggregator, vec,
                            hotlist_db, hotlist_fetcher, hotlist_cfg,
                            rss_db, rss_fetcher, purge_days,
                            archive_enabled=archive_enabled)
                crawl_trigger.mark_done(module)
        except Exception as e:
            logger.error("处理抓取信号失败: %s", e)

        # 定时调度
        for module in ["news", "hotlist", "rss"]:
            timers[module] += 1
            if timers[module] >= intervals[module]:
                timers[module] = 0
                _run_module(module, news_db, aggregator, vec,
                            hotlist_db, hotlist_fetcher, hotlist_cfg,
                            rss_db, rss_fetcher, purge_days,
                            archive_enabled=archive_enabled)

        if monitor_cfg["enabled"]:
            monitor_timer += 1
            if monitor_timer >= monitor_cfg["check_interval"]:
                monitor_timer = 0
                _check_monitor_tasks()

        if wcf_cfg["enabled"]:
            wcf_timer += 1
            if wcf_timer >= wcf_cfg["poll_interval"]:
                wcf_timer = 0
                _poll_wcf_events()


def _get_monitor_config():
    config = load_config()
    monitor_cfg = config.get("monitor", {})
    return {
        "enabled": monitor_cfg.get("enabled", False),
        "check_interval": monitor_cfg.get("check_interval", 60),
        "schedules": monitor_cfg.get("schedules", {
            "daily_morning": "08:00",
            "daily_evening": "20:00",
        }),
    }


def _check_monitor_tasks():
    try:
        from modules.monitor.service import get_monitor_service
        svc = get_monitor_service()
        for task in svc.get_due_tasks():
            t = threading.Thread(target=svc.run_task, args=(task["id"],), daemon=True)
            t.start()
    except Exception as e:
        logger.error("Monitor check failed: %s", e)


def _get_wcf_config():
    config = load_config()
    wcf_cfg = config.get("wcf", {})
    return {
        "enabled": wcf_cfg.get("enabled", False),
        "poll_interval": wcf_cfg.get("poll_interval", 3),
    }


def _poll_wcf_events():
    """轮询 wcfLink 事件：拉取新消息 → 匹配绑定 → 触发 agent 回复。"""
    try:
        from modules.wcf.client import list_events
        from modules.wcf.db import WCFDB
        from modules.wcf.service import WCFService

        db = WCFDB()
        cursor = db.get_cursor()
        events = list_events(after_id=cursor, limit=50)

        if not events:
            return

        svc = WCFService()
        for evt in events:
            evt_id = evt.get("id", 0)
            evt_type = evt.get("type", "")

            # 只处理收到的文本消息
            if evt_type != "message/text":
                db.set_cursor(evt_id)
                continue

            account_id = evt.get("account_id", "")
            user_id = evt.get("from_user_id", evt.get("user_id", ""))
            content = evt.get("content", "")
            if not account_id or not user_id:
                db.set_cursor(evt_id)
                continue

            # 查找是否有绑定的联系人
            binding = db.get_binding_by_user(account_id, user_id)
            if not binding or not binding.get("enabled"):
                db.set_cursor(evt_id)
                continue

            # 记录最后消息
            db.upsert_binding(
                account_id=account_id, user_id=user_id,
                display_name=evt.get("from_nickname", ""),
                last_message=content,
            )

            # 触发 agent 回复
            try:
                reply = svc.chat(
                    session_id=binding["id"],
                    question=content,
                )
                if reply:
                    from modules.wcf.client import send_text
                    send_text(account_id, user_id, reply)
            except Exception as e:
                logger.error("WCF agent reply failed for %s: %s", user_id, e)

            db.set_cursor(evt_id)

    except ImportError as e:
        logger.debug("WCF module not available: %s", e)
    except Exception as e:
        logger.error("WCF event poll failed: %s", e)


def _run_module(module, news_db, aggregator, vec,
                hotlist_db, hotlist_fetcher, hotlist_cfg,
                rss_db, rss_fetcher, purge_days,
                archive_enabled=False):
    try:
        if module == "news":
            _run_news(news_db, aggregator, vec, purge_days,
                      archive_enabled=archive_enabled)
        elif module == "hotlist":
            _run_hotlist(hotlist_db, hotlist_fetcher, hotlist_cfg, vec,
                         archive_enabled=archive_enabled)
        elif module == "rss":
            _run_rss(rss_db, rss_fetcher, purge_days, vec,
                     archive_enabled=archive_enabled)
    except Exception as e:
        logger.error("%s 采集异常: %s", module, e)


def _run_news(db, aggregator, vec, purge_days, archive_enabled=False):
    skip_purge = archive_enabled
    result = aggregator.fetch_and_store(purge_days=purge_days, skip_purge=skip_purge)
    new_items = result.get("new_items", [])
    new_row_ids = result.get("new_row_ids", [])

    if new_items and vec.is_healthy():
        try:
            pipe_result = vec.pipeline_news(new_items, new_row_ids)
            if "error" in pipe_result:
                logger.error("向量管线失败: %s", pipe_result.get("error"))
            else:
                removed_ids = pipe_result.get("removed_row_ids", [])
                if removed_ids:
                    conn = db._get_conn()
                    placeholders = ",".join("?" * len(removed_ids))
                    conn.execute(
                        f"DELETE FROM news WHERE id IN ({placeholders})", removed_ids
                    )
                    conn.commit()
                    conn.close()
                    logger.info("语义去重: 从 SQLite 删除 %d 条", len(removed_ids))

                kept_row_ids = pipe_result.get("kept_row_ids", [])
                categories = pipe_result.get("categories", [])
                cluster_ids = pipe_result.get("cluster_ids", [])
                if kept_row_ids and categories:
                    conn = db._get_conn()
                    for rid, cat, cid in zip(kept_row_ids, categories, cluster_ids):
                        cat_json = json.dumps(cat, ensure_ascii=False) if isinstance(cat, list) else cat
                        conn.execute(
                            "UPDATE news SET category = ?, cluster_id = ? WHERE id = ?",
                            (cat_json, cid, rid),
                        )
                    conn.commit()
                    conn.close()
        except Exception as e:
            logger.error("向量管线异常: %s", e)

    if archive_enabled and vec.is_healthy():
        try:
            vec.archive_migrate_news()
        except Exception as e:
            logger.error("新闻归档迁移失败: %s", e)
    elif not archive_enabled and result["purged"] > 0 and vec.is_healthy():
        try:
            vec.purge_news()
        except Exception as e:
            logger.error("ChromaDB 清理失败: %s", e)

    logger.info(
        "新闻: 原始%d, 新增%d, 清理%d",
        result["total_raw"], result["new_added"], result["purged"],
    )


def _run_hotlist(db, fetcher, config, vec, archive_enabled=False):
    platforms = config.get("platforms") or None
    items, failed = fetcher.fetch_all_platforms(platforms)
    crawl_time = datetime.now().isoformat()
    inserted = db.insert_batch(items, crawl_time)
    new_count = inserted["new"] if isinstance(inserted, dict) else inserted

    if new_count > 0 and vec.is_healthy():
        try:
            conn = db._get_conn()
            rows = conn.execute(
                "SELECT id, title, url, platform, platform_name, hot_rank, crawl_time "
                "FROM hot_items WHERE crawl_time = ?",
                (crawl_time,),
            ).fetchall()
            conn.close()
            if rows:
                vector_items = [dict(r) for r in rows]
                vec.pipeline_hotlist(vector_items)
        except Exception as e:
            logger.error("热榜向量化失败: %s", e)

    if archive_enabled and vec.is_healthy():
        try:
            vec.archive_migrate_hotlist()
        except Exception as e:
            logger.error("热榜归档迁移失败: %s", e)
    else:
        purged = db.purge_old(days=7)
        if purged > 0 and vec.is_healthy():
            try:
                conn = db._get_conn()
                existing_ids = [r[0] for r in conn.execute("SELECT id FROM hot_items").fetchall()]
                conn.close()
                vec.purge_hotlist(existing_ids)
            except Exception as e:
                logger.error("热榜 ChromaDB 清理失败: %s", e)

    logger.info("热榜: 抓取%d条, 新增%d条, 更新%d条, 失败%d平台",
                len(items), new_count,
                inserted.get("updated", 0) if isinstance(inserted, dict) else 0,
                len(failed))


def _run_rss(db, fetcher, purge_days, vec, archive_enabled=False):
    result = fetcher.fetch_and_store(db)

    if result.get("total_items", 0) > 0 and vec.is_healthy():
        try:
            feeds = db.get_feeds(enabled_only=True)
            all_items = []
            for feed in feeds:
                items = db.get_items(feed_id=feed["id"], days=1, page=1, page_size=50)
                for it in items["items"]:
                    it["feed_name"] = feed["name"]
                all_items.extend(items["items"])
            if all_items:
                vec.pipeline_rss(all_items)
        except Exception as e:
            logger.error("RSS 向量化失败: %s", e)

    if archive_enabled and vec.is_healthy():
        try:
            vec.archive_migrate_rss()
        except Exception as e:
            logger.error("RSS 归档迁移失败: %s", e)
    else:
        purged = db.purge_old(days=purge_days)
        if purged > 0 and vec.is_healthy():
            try:
                conn = db._get_conn()
                existing_ids = [r[0] for r in conn.execute("SELECT id FROM rss_items").fetchall()]
                conn.close()
                vec.purge_rss(existing_ids)
            except Exception as e:
                logger.error("RSS ChromaDB 清理失败: %s", e)

    logger.info(
        "RSS: 获取%d源, 失败%d, 共%d条",
        result.get("fetched", 0), result.get("failed", 0), result.get("total_items", 0),
    )


if __name__ == "__main__":
    main()

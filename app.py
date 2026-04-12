"""
信源汇总 - Flask 应用入口

六模块：新闻汇总 + 热榜 + RSS订阅 + 热点选题 + 文案创作 + 智能问答
"""
import sqlite3
import os
from flask import Flask, send_from_directory, jsonify
from utils.config import load_config
from modules.news.routes import news_bp
from modules.hotlist.routes import hotlist_bp
from modules.rss.routes import rss_bp
from modules.topic.routes import topic_bp
from modules.creator.routes import creator_bp
from modules.chat.routes import chat_bp
from modules.archive.routes import archive_bp

# React 构建产物目录
_REACT_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend_dist")

app = Flask(__name__, static_folder=os.path.join(_REACT_DIST, "assets"))
app.config["JSON_AS_ASCII"] = False

# 加载全局配置
_config = load_config()
if _config:
    proxy_url = _config.get("proxy", {}).get("url")
    if proxy_url:
        app.config["PROXY_URL"] = proxy_url

    rsshub_cfg = _config.get("rsshub", {})
    if rsshub_cfg:
        app.config["RSSHUB_CONFIG"] = rsshub_cfg

# 注册 Blueprint
app.register_blueprint(news_bp)
app.register_blueprint(hotlist_bp)
app.register_blueprint(rss_bp)
app.register_blueprint(topic_bp)
app.register_blueprint(creator_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(archive_bp)


@app.route("/")
def index():
    return send_from_directory(_REACT_DIST, "index.html")


@app.route("/<path:path>", methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def spa_fallback(path):
    """React SPA fallback: 非 API、非文件路由返回 index.html"""
    # /api/* 未命中任何已注册路由时，返回 JSON 404 而非前端 HTML
    if path.startswith("api/"):
        return jsonify({"error": "API endpoint not found", "path": f"/{path}"}), 404

    file_path = os.path.join(_REACT_DIST, path)
    if os.path.isfile(file_path):
        return send_from_directory(_REACT_DIST, path)
    return send_from_directory(_REACT_DIST, "index.html")


@app.route("/api/status")
def api_status():
    """全局状态"""
    from modules.news.db import NewsDB
    from modules.hotlist.db import HotlistDB
    from modules.rss.db import RSSDB

    status = {}
    try:
        news_db = NewsDB()
        count = news_db.get_count()
        status["news_count"] = count
        status["news"] = {"count": count, "available": True}
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError):
        status["news_count"] = 0
        status["news"] = {"count": 0, "available": False}

    try:
        hotlist_db = HotlistDB()
        last_crawl = hotlist_db.get_last_crawl_time()
        status["hotlist_last_crawl"] = last_crawl
        status["hotlist"] = {"last_crawl": last_crawl, "available": True}
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError):
        status["hotlist"] = {"available": False}

    try:
        rss_db = RSSDB()
        feeds = rss_db.get_feeds()
        status["rss_feed_count"] = len(feeds)
        status["rss"] = {"feed_count": len(feeds), "available": True}
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError):
        status["rss_feed_count"] = 0
        status["rss"] = {"available": False}

    # AI 模块状态
    try:
        from ai import AI_AVAILABLE
        status["ai_available"] = AI_AVAILABLE
        status["ai"] = {"available": AI_AVAILABLE}
    except (ImportError, ModuleNotFoundError):
        status["ai_available"] = False
        status["ai"] = {"available": False}

    return jsonify(status)


@app.route("/api/scheduler/health")
def scheduler_health():
    """检查 scheduler 向量服务状态"""
    from utils.scheduler_client import is_scheduler_alive
    alive = is_scheduler_alive()
    return jsonify({"scheduler": alive}), 200 if alive else 503


if __name__ == "__main__":
    import argparse
    import webbrowser

    # 加载 .env 环境变量
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    # 仅主进程（非 watchdog 重启子进程）才开浏览器
    if not args.no_browser and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        webbrowser.open(f"http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)

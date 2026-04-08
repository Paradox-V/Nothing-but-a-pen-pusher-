"""
信源汇总 - Flask 应用入口

六模块：新闻汇总 + 热榜 + RSS订阅 + 热点选题 + 文案创作 + 智能问答
"""
import webbrowser
from flask import Flask, render_template, jsonify
from utils.config import load_config
from modules.news.routes import news_bp
from modules.hotlist.routes import hotlist_bp
from modules.rss.routes import rss_bp
from modules.topic.routes import topic_bp
from modules.creator.routes import creator_bp
from modules.chat.routes import chat_bp

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False  # 中文不转义

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


@app.route("/")
def index():
    return render_template("index.html")


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
        status["news"] = {"count": count, "available": True}
    except Exception:
        status["news"] = {"count": 0, "available": False}

    try:
        hotlist_db = HotlistDB()
        last_crawl = hotlist_db.get_last_crawl_time()
        status["hotlist"] = {"last_crawl": last_crawl, "available": True}
    except Exception:
        status["hotlist"] = {"available": False}

    try:
        rss_db = RSSDB()
        feeds = rss_db.get_feeds()
        status["rss"] = {"feed_count": len(feeds), "available": True}
    except Exception:
        status["rss"] = {"available": False}

    # AI 模块状态
    try:
        from ai import AI_AVAILABLE
        status["ai"] = {"available": AI_AVAILABLE}
    except Exception:
        status["ai"] = {"available": False}

    return jsonify(status)


if __name__ == "__main__":
    import argparse
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    # 仅主进程（非 watchdog 重启子进程）才开浏览器
    if not args.no_browser and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        webbrowser.open(f"http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)

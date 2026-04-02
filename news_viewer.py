"""
AKTools 信源聚合阅览器 —— Web UI

数据从 SQLite 读取。定时采集由独立的 scheduler_runner.py 进程负责。
本服务仅提供查询接口和手动触发抓取功能。
集成语义搜索、分类筛选、专题聚合。
"""

import json
import logging
import os
import threading
import webbrowser

# 离线模式：跳过 HuggingFace 网络检查，直接使用本地缓存
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

from flask import Flask, jsonify, render_template_string, request

from ak_source_aggregator import AKSourceAggregator, NewsDB

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── 全局组件 ──────────────────────────────────────────────
import os as _os
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
_DB_PATH = _os.path.join(_BASE_DIR, "news.db")
_CHROMA_DIR = _os.path.join(_BASE_DIR, "chroma_db")

db = NewsDB(_DB_PATH)
agg = AKSourceAggregator(db=db)
_fetching = False

# 启动时自动迁移旧数据
try:
    migrated = db.migrate_category_to_json()
    if migrated > 0:
        logger.info("数据迁移完成: %d 条旧数据已转为 JSON 数组格式", migrated)
except Exception as e:
    logger.error("数据迁移失败: %s", e)

# 延迟加载向量引擎（避免启动时加载模型）
_vector_engine = None


def _get_vector_engine():
    global _vector_engine
    if _vector_engine is None:
        try:
            from news_vector import NewsVectorEngine
            _vector_engine = NewsVectorEngine(
                db_path=_DB_PATH,
                chroma_dir=_CHROMA_DIR,
            )
            _vector_engine.initialize()
            logger.info("向量引擎加载成功")
        except Exception as e:
            logger.error("向量引擎加载失败: %s", e)
            return None
    return _vector_engine


# ── HTML 页面 ──────────────────────────────────────────────
PAGE_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AKTools 信源聚合阅览器</title>
<style>
  :root {
    --bg: #0f1117; --card: #1a1d27; --border: #2a2d3a;
    --fg: #e1e4ea; --muted: #8b8fa3; --accent: #4f8ff7;
    --green: #34d399; --red: #f87171; --orange: #fbbf24;
    --tag-bg: #262a3a; --purple: #a78bfa;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    background:var(--bg); color:var(--fg); line-height:1.6;
  }
  .header {
    background:linear-gradient(135deg,#1a1d27,#141622);
    border-bottom:1px solid var(--border);
    padding:20px 32px; position:sticky; top:0; z-index:100;
  }
  .header h1 { font-size:22px; font-weight:700; margin-bottom:6px; }
  .header .meta { color:var(--muted); font-size:13px; }
  .header .meta span { margin-right:16px; }
  .sched-badge {
    display:inline-block; padding:2px 10px; border-radius:12px;
    font-size:12px; margin-left:12px;
  }
  .sched-badge.on { background:#1a3a2a; color:var(--green); }
  .sched-badge.off { background:#3a2a1a; color:var(--orange); }
  .controls {
    display:flex; gap:12px; align-items:center;
    padding:16px 32px; border-bottom:1px solid var(--border); flex-wrap:wrap;
  }
  .controls input[type="text"] {
    flex:1; min-width:200px; padding:8px 14px;
    background:var(--card); border:1px solid var(--border);
    border-radius:6px; color:var(--fg); font-size:14px; outline:none;
  }
  .controls input:focus { border-color:var(--accent); }
  .search-wrap {
    display:flex; flex:1; min-width:200px; position:relative;
  }
  .search-wrap input {
    flex:1; padding:8px 40px 8px 14px;
    background:var(--card); border:1px solid var(--border);
    border-radius:6px; color:var(--fg); font-size:14px; outline:none;
  }
  .search-wrap input:focus { border-color:var(--accent); }
  .search-btn {
    position:absolute; right:4px; top:50%; transform:translateY(-50%);
    background:none; border:none; color:var(--muted); font-size:18px;
    cursor:pointer; padding:4px 8px; line-height:1;
  }
  .search-btn:hover { color:var(--accent); }
  .search-wrap {
    display:flex; flex:1; min-width:200px; position:relative;
  }
  .search-wrap input {
    flex:1; padding:8px 40px 8px 14px;
    background:var(--card); border:1px solid var(--border);
    border-radius:6px; color:var(--fg); font-size:14px; outline:none;
  }
  .search-wrap input:focus { border-color:var(--accent); }
  .search-btn {
    position:absolute; right:4px; top:50%; transform:translateY(-50%);
    background:none; border:none; color:var(--muted); font-size:18px;
    cursor:pointer; padding:4px 8px; line-height:1;
  }
  .search-btn:hover { color:var(--accent); }
  .controls select, .controls button {
    padding:8px 16px; background:var(--card);
    border:1px solid var(--border); border-radius:6px;
    color:var(--fg); font-size:14px; cursor:pointer;
  }
  .controls button:hover { border-color:var(--accent); color:var(--accent); }
  .btn-fetch {
    background:var(--accent)!important; color:#fff!important;
    border-color:var(--accent)!important; font-weight:600;
  }
  .btn-fetch:hover { opacity:0.85; }
  .btn-fetch:disabled { opacity:0.5; cursor:not-allowed; }
  /* 语义搜索切换 */
  .search-mode-toggle {
    display:flex; align-items:center; gap:6px; font-size:13px; color:var(--muted);
  }
  .search-mode-toggle label { cursor:pointer; }
  .search-mode-toggle input[type="checkbox"] { cursor:pointer; }
  /* 信源栏 + 日期滑块同行 */
  .source-row {
    display:flex; align-items:flex-start; gap:16px; padding:12px 32px;
    border-bottom:1px solid var(--border); flex-wrap:wrap;
  }
  .source-pills {
    display:flex; gap:8px; flex-wrap:wrap; flex:1;
  }
  /* 日期范围滑块 */
  .date-range-wrap {
    display:flex; flex-direction:column; gap:4px; min-width:220px; max-width:280px;
    padding-top:2px;
  }
  .date-label {
    text-align:center; font-size:12px; color:var(--accent); font-weight:500;
    min-height:18px;
  }
  .range-slider {
    position:relative; height:20px; user-select:none; touch-action:none;
  }
  .range-track {
    position:absolute; top:8px; left:0; right:0; height:4px;
    background:var(--border); border-radius:2px;
  }
  .range-fill {
    position:absolute; top:8px; height:4px;
    background:var(--accent); border-radius:2px;
  }
  .range-thumb {
    position:absolute; top:2px; width:16px; height:16px;
    background:var(--fg); border:2px solid var(--accent);
    border-radius:50%; cursor:grab; z-index:2;
    transition:transform .1s;
  }
  .range-thumb:hover { transform:scale(1.2); }
  .range-thumb:active { cursor:grabbing; transform:scale(1.3); }
  .range-ticks {
    display:flex; justify-content:space-between;
    font-size:10px; color:var(--muted); padding:0 4px;
  }
  /* 标签页 */
  .tabs {
    display:flex; gap:0; border-bottom:1px solid var(--border);
    padding:0 32px;
  }
  .tab-btn {
    padding:10px 20px; background:transparent; border:none;
    border-bottom:2px solid transparent; color:var(--muted);
    font-size:14px; cursor:pointer; font-weight:500;
  }
  .tab-btn:hover { color:var(--fg); }
  .tab-btn.active { color:var(--accent); border-bottom-color:var(--accent); }
  .tab-content { display:none; }
  .tab-content.active { display:block; }
  /* 分类标签 */
  .category-bar {
    display:flex; gap:8px; padding:12px 32px; flex-wrap:wrap;
    border-bottom:1px solid var(--border);
  }
  .cat-pill {
    display:flex; align-items:center; gap:4px;
    background:var(--card); border:1px solid var(--border);
    border-radius:20px; padding:4px 12px; font-size:12px;
    cursor:pointer; transition:all .2s;
  }
  .cat-pill:hover { border-color:var(--accent); color:var(--accent); }
  .cat-pill.active { background:var(--accent); color:#fff; border-color:var(--accent); }
  .cat-pill .cnt { color:var(--muted); font-size:11px; }
  .cat-pill.active .cnt { color:rgba(255,255,255,0.7); }
  .source-bar { display:flex; gap:8px; padding:0 32px 16px; flex-wrap:wrap; }
  .source-pill {
    display:flex; align-items:center; gap:6px;
    background:var(--card); border:1px solid var(--border);
    border-radius:20px; padding:6px 14px; font-size:13px;
  }
  .source-pill .dot { width:8px; height:8px; border-radius:50%; background:var(--green); }
  .source-pill .count { color:var(--muted); font-size:12px; }
  .news-grid { display:flex; flex-direction:column; gap:10px; padding:0 32px 40px; }
  .news-card {
    background:var(--card); border:1px solid var(--border);
    border-radius:8px; padding:16px 20px; transition:border-color .2s;
  }
  .news-card:hover { border-color:var(--accent); }
  .news-card .top-row {
    display:flex; align-items:center; gap:10px; margin-bottom:8px; flex-wrap:wrap;
  }
  .news-card .source-badge {
    background:var(--tag-bg); padding:2px 10px;
    border-radius:12px; font-size:12px; color:var(--accent); white-space:nowrap;
  }
  .news-card .cat-badge {
    background:#1a2a3a; padding:2px 10px;
    border-radius:12px; font-size:12px; color:var(--purple); white-space:nowrap;
  }
  .news-card .similarity-badge {
    background:#1a3a1a; padding:2px 10px;
    border-radius:12px; font-size:12px; color:var(--green); white-space:nowrap;
  }
  .news-card .timestamp { color:var(--muted); font-size:12px; }
  .news-card .title { font-size:15px; font-weight:600; margin-bottom:6px; }
  .news-card .content {
    font-size:14px; color:var(--muted); line-height:1.7;
    display:-webkit-box; -webkit-line-clamp:3;
    -webkit-box-orient:vertical; overflow:hidden;
  }
  .news-card.expanded .content { -webkit-line-clamp:unset; overflow:auto; }
  .news-card .bottom-row {
    display:flex; align-items:center; gap:8px; margin-top:8px;
  }
  .news-card .tag {
    background:var(--tag-bg); padding:2px 8px;
    border-radius:4px; font-size:11px; color:var(--muted);
  }
  .news-card .link {
    font-size:12px; color:var(--accent); text-decoration:none; margin-left:auto;
  }
  .news-card .link:hover { text-decoration:underline; }
  .empty-state { text-align:center; padding:80px 20px; color:var(--muted); }
  .empty-state .icon { font-size:48px; margin-bottom:12px; }
  .pagination { display:flex; justify-content:center; gap:8px; padding:20px 32px; }
  .pagination button {
    padding:6px 14px; background:var(--card);
    border:1px solid var(--border); border-radius:6px;
    color:var(--fg); cursor:pointer; font-size:13px;
  }
  .pagination button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
  .pagination button:disabled { opacity:.4; cursor:not-allowed; }
  .loading { text-align:center; padding:40px; color:var(--muted); }
  @keyframes spin { to { transform:rotate(360deg); } }
</style>
</head>
<body>

<div class="header">
  <h1>&#x1F4F0; AKTools 信源聚合阅览器
    <span class="sched-badge on" id="schedBadge">定时采集中</span>
  </h1>
  <div class="meta" id="headerMeta">加载中...</div>
</div>

<div class="controls">
  <div class="search-wrap">
    <input type="text" id="searchInput" placeholder="搜索标题或内容..." onkeydown="if(event.key==='Enter')doSearch()">
    <button class="search-btn" onclick="doSearch()" title="搜索">&#128269;</button>
  </div>
  <div class="search-mode-toggle">
    <input type="checkbox" id="semanticToggle">
    <label for="semanticToggle">语义搜索</label>
  </div>
  <button class="btn-fetch" id="btnFetch" onclick="doFetch()">立即抓取</button>
</div>

<!-- 分类标签栏 -->
<div class="category-bar" id="categoryBar"></div>

<!-- 信源标签栏 + 日期滑块（仅新闻列表标签页显示） -->
<div class="source-row" id="sourceRow">
  <div class="source-pills" id="sourceBar"></div>
  <div class="date-range-wrap">
    <span class="date-label" id="dateLabel">全部时间</span>
    <div class="range-slider" id="rangeSlider">
      <div class="range-track"></div>
      <div class="range-fill" id="rangeFill"></div>
      <div class="range-thumb" id="thumbLeft" data-side="left"></div>
      <div class="range-thumb" id="thumbRight" data-side="right"></div>
    </div>
    <div class="range-ticks">
      <span>7天前</span><span>5天前</span><span>3天前</span><span>昨天</span><span>今天</span>
    </div>
  </div>
</div>

<!-- 新闻列表 -->
<div class="news-grid" id="newsGrid"></div>

<script>
const PER_PAGE = 30;
let currentPage = 1;
let totalCount = 0;
let searchTimer = null;
let currentTab = 'news';
let activeCategories = new Set();
let activeSources = new Set();
let allSources = [];
const SLIDER_DAYS = 7; // 滑块覆盖的天数范围

// ── 双向日期滑块 ──────────────────────────────
let rangeMin = 0;   // 0 = 7天前
let rangeMax = 7;   // 7 = 今天

function initRangeSlider() {
  const slider = document.getElementById('rangeSlider');
  const fill = document.getElementById('rangeFill');
  const thumbL = document.getElementById('thumbLeft');
  const thumbR = document.getElementById('thumbRight');
  const W = slider.offsetWidth;

  function posToDay(x) { return Math.round(Math.max(0, Math.min(SLIDER_DAYS, (x / W) * SLIDER_DAYS))); }
  function dayToPos(d) { return (d / SLIDER_DAYS) * W; }

  function render() {
    const pL = dayToPos(rangeMin);
    const pR = dayToPos(rangeMax);
    thumbL.style.left = (pL - 8) + 'px';
    thumbR.style.left = (pR - 8) + 'px';
    fill.style.left = pL + 'px';
    fill.style.width = (pR - pL) + 'px';
    updateDateLabel();
  }

  function updateDateLabel() {
    if (rangeMin === 0 && rangeMax === SLIDER_DAYS) {
      document.getElementById('dateLabel').textContent = '全部时间';
      return;
    }
    const from = daysAgoToStr(SLIDER_DAYS - rangeMin);
    const to = daysAgoToStr(SLIDER_DAYS - rangeMax);
    document.getElementById('dateLabel').textContent = from + ' 至 ' + to;
  }

  function daysAgoToStr(daysAgo) {
    if (daysAgo <= 0) return '今天';
    if (daysAgo === 1) return '昨天';
    return daysAgo + '天前';
  }

  let dragging = null;
  function onDown(e) {
    e.preventDefault();
    const thumb = e.target;
    dragging = thumb.dataset.side;
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.addEventListener('touchmove', onMove, {passive:false});
    document.addEventListener('touchend', onUp);
  }
  function onMove(e) {
    if (!dragging) return;
    e.preventDefault();
    const rect = slider.getBoundingClientRect();
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
    const day = posToDay(x);
    if (dragging === 'left') {
      rangeMin = Math.min(day, rangeMax - 1);
    } else {
      rangeMax = Math.max(day, rangeMin + 1);
    }
    render();
  }
  function onUp() {
    dragging = null;
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    document.removeEventListener('touchmove', onMove);
    document.removeEventListener('touchend', onUp);
    currentPage = 1;
    loadNews();
  }

  thumbL.addEventListener('mousedown', onDown);
  thumbR.addEventListener('mousedown', onDown);
  thumbL.addEventListener('touchstart', onDown, {passive:false});
  thumbR.addEventListener('touchstart', onDown, {passive:false});

  // 双击重置
  slider.addEventListener('dblclick', () => {
    rangeMin = 0; rangeMax = SLIDER_DAYS;
    render();
    currentPage = 1;
    loadNews();
  });

  render();
}

function getDateFrom() {
  if (rangeMin === 0 && rangeMax === SLIDER_DAYS) return null;
  const d = new Date(); d.setDate(d.getDate() - (SLIDER_DAYS - rangeMin));
  return d.toISOString().slice(0, 10);
}
function getDateTo() {
  if (rangeMin === 0 && rangeMax === SLIDER_DAYS) return null;
  const d = new Date(); d.setDate(d.getDate() - (SLIDER_DAYS - rangeMax));
  return d.toISOString().slice(0, 10);
}

function debounceSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { currentPage = 1; loadNews(); }, 300);
}

function doSearch() {
  currentPage = 1;
  loadNews();
}

function esc(s) { return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }

// ── 分类标签（多选） ──────────────────────────────
async function loadCategories() {
  try {
    const resp = await fetch('/api/categories');
    const cats = await resp.json();
    const bar = document.getElementById('categoryBar');
    let html = '<div class="cat-pill' + (activeCategories.size === 0 ? ' active' : '') +
      '" onclick="clearCategories()">全部</div>';
    cats.forEach(c => {
      const isActive = activeCategories.has(c.category);
      html += '<div class="cat-pill' + (isActive ? ' active' : '') +
        '" onclick="toggleCategory(\'' + esc(c.category) + '\')">' +
        esc(c.category) + ' <span class="cnt">' + c.count + '</span></div>';
    });
    bar.innerHTML = html;
  } catch(e) {}
}

function toggleCategory(cat) {
  if (activeCategories.has(cat)) {
    activeCategories.delete(cat);
  } else {
    activeCategories.add(cat);
  }
  currentPage = 1;
  loadCategories();
  loadNews();
}

function clearCategories() {
  activeCategories.clear();
  currentPage = 1;
  loadCategories();
  loadNews();
}

// ── 信源标签（多选） ──────────────────────────────
function renderSourceBar(data) {
  const pills = document.querySelector('.source-pills');
  if (!pills) return;
  const stats = data.source_stats || {};
  allSources = Object.keys(stats);

  let html = '<div class="cat-pill' + (activeSources.size === 0 ? ' active' : '') +
    '" onclick="clearSources()">全部信源</div>';
  for (const [name, count] of Object.entries(stats)) {
    const isActive = activeSources.has(name);
    html += '<div class="cat-pill' + (isActive ? ' active' : '') +
      '" onclick="toggleSource(\'' + esc(name) + '\')">' +
      esc(name) + ' <span class="cnt">' + count + '</span></div>';
  }
  pills.innerHTML = html;
}

function toggleSource(src) {
  if (activeSources.has(src)) {
    activeSources.delete(src);
  } else {
    activeSources.add(src);
  }
  currentPage = 1;
  renderSourceBar({ source_stats: Object.fromEntries(allSources.map(s => [s, 0])) });
  // 重新获取真实计数
  loadSourceStats();
  loadNews();
}

function clearSources() {
  activeSources.clear();
  currentPage = 1;
  loadSourceStats();
  loadNews();
}

async function loadSourceStats() {
  try {
    const resp = await fetch('/api/status');
    const data = await resp.json();
    renderSourceBar(data);
  } catch(e) {}
}

// ── 抓取 ──────────────────────────────────────
async function doFetch() {
  const btn = document.getElementById('btnFetch');
  btn.disabled = true; btn.textContent = '抓取中...';
  try {
    const resp = await fetch('/api/fetch');
    const data = await resp.json();
    currentPage = 1;
    renderSourceBar(data);
    loadCategories();
    loadNews();
    document.getElementById('headerMeta').innerHTML =
      `<span>抓取时间: ${data.fetch_time || '-'}</span><span>数据库: ${data.db_total ?? '-'} 条</span>`;
  } catch(e) { alert('抓取失败: ' + e.message); }
  finally { btn.disabled = false; btn.textContent = '立即抓取'; }
}

// ── 新闻列表 ──────────────────────────────────────
async function loadNews() {
  const keyword = document.getElementById('searchInput').value.trim();
  const semantic = document.getElementById('semanticToggle').checked;

  // 语义搜索模式
  if (semantic && keyword) {
    await loadSemanticSearch(keyword);
    return;
  }

  const params = new URLSearchParams({
    page: currentPage, per_page: PER_PAGE,
  });
  if (keyword) params.set('keyword', keyword);
  if (activeCategories.size > 0) params.set('categories', [...activeCategories].join(','));
  if (activeSources.size > 0) params.set('sources', [...activeSources].join(','));
  const dateFrom = getDateFrom();
  const dateTo = getDateTo();
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);

  const resp = await fetch('/api/news?' + params);
  const data = await resp.json();
  totalCount = data.total;
  renderNews(data.items);
}

async function loadSemanticSearch(query) {
  const params = new URLSearchParams({
    q: query, n: PER_PAGE,
  });
  if (activeCategories.size > 0) params.set('categories', [...activeCategories].join(','));
  if (activeSources.size > 0) params.set('sources', [...activeSources].join(','));

  // 显示加载状态，避免用户以为卡死
  const grid = document.getElementById('newsGrid');
  grid.innerHTML = '<div class="empty-state"><div class="icon" style="animation:spin 1s linear infinite">&#x2699;</div><div>正在加载语义搜索模型，请稍候...</div></div>';

  try {
    const resp = await fetch('/api/semantic_search?' + params);
    if (!resp.ok) throw new Error(resp.statusText);
    const items = await resp.json();
    if (items.error) throw new Error(items.error);
    totalCount = items.length;
    renderNews(items, true);
  } catch(e) {
    // 语义搜索不可用时回退到普通搜索
    document.getElementById('semanticToggle').checked = false;
    await loadNews();
    document.getElementById('newsGrid').insertAdjacentHTML('afterbegin',
      '<div style="padding:8px 16px;background:#3a2a1a;color:var(--orange);border-radius:6px;margin-bottom:8px;font-size:13px;">' +
      '语义搜索暂不可用，已切换为关键词搜索</div>');
  }
}

function renderNews(items, showSimilarity = false) {
  const grid = document.getElementById('newsGrid');
  if (!items || !items.length) {
    grid.innerHTML = '<div class="empty-state"><div class="icon">&#x1F4ED;</div><div>暂无新闻，点击「立即抓取」启动采集</div></div>';
    return;
  }
  grid.innerHTML = '';
  items.forEach(n => {
    const tags = (n.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('');
    const link = n.url ? `<a class="link" href="${esc(n.url)}" target="_blank" rel="noopener">查看原文 &rarr;</a>` : '';
    const ts = n.timestamp ? n.timestamp.replace('T',' ').slice(0,19) : (n.created_at||'').slice(0,19);
    // category 是数组，渲染多个 badge
    const cats = Array.isArray(n.category) ? n.category : (n.category ? [n.category] : []);
    const catBadges = cats.map(c => `<span class="cat-badge">${esc(c)}</span>`).join('');
    const simBadge = (showSimilarity && n.similarity !== undefined)
      ? `<span class="similarity-badge">${(n.similarity*100).toFixed(0)}%</span>` : '';
    const card = document.createElement('div');
    card.className = 'news-card';
    card.innerHTML = `
      <div class="top-row">
        <span class="source-badge">${esc(n.source_name)}</span>
        ${catBadges}${simBadge}
        <span class="timestamp">${ts}</span>
      </div>
      <div class="title">${esc(n.title)}</div>
      <div class="content">${esc(n.content)}</div>
      <div class="bottom-row">${tags}${link}</div>`;
    card.addEventListener('click', () => card.classList.toggle('expanded'));
    grid.appendChild(card);
  });
  const totalPages = Math.ceil(totalCount / PER_PAGE) || 1;
  grid.innerHTML += `<div class="pagination">
    <button onclick="goto(1)" ${currentPage===1?'disabled':''}>&laquo;</button>
    <button onclick="goto(${currentPage-1})" ${currentPage===1?'disabled':''}>&lsaquo; 上一页</button>
    <button class="active">${currentPage} / ${totalPages} (共${totalCount}条)</button>
    <button onclick="goto(${currentPage+1})" ${currentPage>=totalPages?'disabled':''}>下一页 &rsaquo;</button>
    <button onclick="goto(${totalPages})" ${currentPage>=totalPages?'disabled':''}>&raquo;</button>
  </div>`;
}

function goto(p) {
  currentPage = p; loadNews();
  document.querySelector('.news-grid').scrollIntoView({behavior:'smooth',block:'start'});
}

// 初始化：加载状态 + 新闻
(async function init() {
  try {
    const resp = await fetch('/api/status');
    const data = await resp.json();
    renderSourceBar(data);
    document.getElementById('headerMeta').innerHTML =
      `<span>数据库: ${data.db_total ?? '-'} 条</span>`;
  } catch(e) {}
  initRangeSlider();
  loadCategories();
  loadNews();
})();
</script>
</body>
</html>
"""


# ── Flask 路由 ────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(PAGE_HTML)


@app.route("/api/status")
def api_status():
    stats = db.get_source_stats()
    return jsonify({
        "db_total": db.get_total_count(),
        "source_stats": stats,
        "sources_count": len(stats),
        "sources": db.get_sources_list(),
    })


@app.route("/api/news")
def api_news():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 30, type=int)
    keyword = request.args.get("keyword")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    offset = (page - 1) * per_page

    # 多值 source 参数: ?sources=A,B 或 ?source=A,B
    source = request.args.get("source") or request.args.get("sources")
    sources = source.split(",") if source else None

    # 多值 category 参数: ?categories=A,B 或 ?category=A,B
    category = request.args.get("category") or request.args.get("categories")
    categories = category.split(",") if category else None

    items = db.get_all(
        sources=sources, categories=categories, keyword=keyword,
        date_from=date_from, date_to=date_to,
        limit=per_page, offset=offset,
    )
    total = db.get_count(
        sources=sources, categories=categories, keyword=keyword,
        date_from=date_from, date_to=date_to,
    )

    return jsonify({"items": items, "total": total, "page": page, "per_page": per_page})


@app.route("/api/semantic_search")
def api_semantic_search():
    query = request.args.get("q", "")
    n = request.args.get("n", 20, type=int)

    # 多值 category
    category = request.args.get("category") or request.args.get("categories")
    categories = category.split(",") if category else None

    # 多值 source
    source = request.args.get("source") or request.args.get("sources")
    sources = source.split(",") if source else None

    if not query:
        return jsonify([])

    engine = _get_vector_engine()
    if not engine:
        return jsonify({"error": "向量引擎未就绪"}), 503

    results = engine.semantic_search(
        query=query, n=n, categories=categories, sources=sources,
    )
    return jsonify(results)


@app.route("/api/categories")
def api_categories():
    return jsonify(db.get_category_stats())


@app.route("/api/clusters")
def api_clusters():
    return jsonify(db.get_cluster_list())


@app.route("/api/cluster/<path:cluster_id>")
def api_cluster_detail(cluster_id):
    items = db.get_cluster_news(cluster_id)
    return jsonify(items)


@app.route("/api/fetch")
def api_fetch():
    global _fetching
    if _fetching:
        return jsonify({"error": "正在抓取中，请稍候"}), 409
    _fetching = True
    try:
        result = agg.fetch_and_store(purge_days=7)

        # 手动抓取也运行向量处理管线
        new_items = result.get("new_items", [])
        new_row_ids = result.get("new_row_ids", [])
        if new_items:
            engine = _get_vector_engine()
            if engine:
                _run_vector_pipeline(engine, new_items, new_row_ids)
            if result.get("purged", 0) > 0 and engine:
                try:
                    engine.sync_chroma_purge()
                except Exception:
                    pass

        stats = db.get_source_stats()
        return jsonify({
            **result,
            "source_stats": stats,
            "sources_count": len(stats),
            "sources": db.get_sources_list(),
        })
    except Exception as e:
        logger.error("手动抓取失败: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        _fetching = False


def _run_vector_pipeline(vector_engine, items, row_ids):
    """向量处理管线：语义去重 → 分类 → 聚类 → ChromaDB 写入。"""
    import sqlite3
    try:
        deduped = vector_engine.semantic_dedup(items)
        deduped_set = set()
        for d in deduped:
            # 用 (title, content前100字) 作为唯一标识
            deduped_set.add((d["title"], d.get("content", "")[:100]))

        deduped_items = []
        deduped_row_ids = []
        for item, rid in zip(items, row_ids):
            key = (item["title"], item.get("content", "")[:100])
            if key in deduped_set:
                deduped_items.append(item)
                deduped_row_ids.append(rid)

        # 删除语义重复条目
        removed_row_ids = [
            rid for item, rid in zip(items, row_ids)
            if (item["title"], item.get("content", "")[:100]) not in deduped_set
        ]
        if removed_row_ids:
            conn = sqlite3.connect(_DB_PATH)
            placeholders = ",".join("?" * len(removed_row_ids))
            conn.execute(
                f"DELETE FROM news WHERE id IN ({placeholders})",
                removed_row_ids,
            )
            conn.commit()
            conn.close()

        if not deduped_items:
            return

        categories = vector_engine.classify_items(deduped_items)
        cluster_ids = vector_engine.assign_clusters(deduped_items)

        conn = sqlite3.connect(_DB_PATH)
        for rid, cat, cid in zip(deduped_row_ids, categories, cluster_ids):
            cat_json = json.dumps(cat, ensure_ascii=False) if isinstance(cat, list) else cat
            conn.execute(
                "UPDATE news SET category = ?, cluster_id = ? WHERE id = ?",
                (cat_json, cid, rid),
            )
        conn.commit()
        conn.close()

        vector_engine.upsert_to_chroma(
            deduped_items, deduped_row_ids, categories, cluster_ids
        )
    except Exception as e:
        logger.error("向量处理管线异常: %s", e)


@app.route("/api/sources")
def api_sources():
    return jsonify(db.get_source_stats())


# ── 启动入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    port = 5000
    print(f"\n  AKTools 信源聚合阅览器")
    print(f"  地址: http://127.0.0.1:{port}")
    print(f"  按 Ctrl+C 退出\n")

    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False)

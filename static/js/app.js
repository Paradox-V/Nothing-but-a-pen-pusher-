// ── Global state ─────────────────────────────
const PER_PAGE = 30;
let currentTab = 'news';

// ── Auth helper ──────────────────────────────
const AUTH_KEY = '_admin_token';

function getAdminToken() {
  return localStorage.getItem(AUTH_KEY) || '';
}

function setAdminToken(token) {
  if (token) localStorage.setItem(AUTH_KEY, token);
  else localStorage.removeItem(AUTH_KEY);
}

/** 带鉴权的 fetch 包装，所有写操作 (POST/PUT/DELETE) 应使用此函数 */
function authFetch(url, options = {}) {
  const token = getAdminToken();
  if (token) {
    options.headers = options.headers || {};
    options.headers['Authorization'] = 'Bearer ' + token;
  }
  return fetch(url, options);
}

function promptAdminToken() {
  const current = getAdminToken();
  const token = prompt('请输入管理员 Token（可在 .env 中配置 ADMIN_TOKEN）：', current);
  if (token !== null) {
    setAdminToken(token.trim());
    if (token.trim()) showNotice('ok', 'Token 已保存');
    else showNotice('err', 'Token 已清除');
  }
}

// News state
let newsPage = 1;
let newsTotal = 0;
let newsSearchTimer = null;
let activeCategories = new Set();
let activeSources = new Set();
let allSources = [];
const SLIDER_DAYS = 7;
let rangeMin = 0;
let rangeMax = 7;

// Hotlist state
let hotPage = 1;
let hotTotal = 0;
let hotPlatforms = [];

// RSS state
let rssPage = 1;
let rssTotal = 0;
let rssFeeds = [];

// ── Utility ──────────────────────────────────
function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/`/g,'&#96;');
}
function safeMarkdown(md) {
  if (!md) return '';
  const raw = typeof marked !== 'undefined' ? marked.parse(md) : esc(md).replace(/\n/g,'<br>');
  return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(raw) : raw;
}

function renderPagination(container, page, total, perPage, gotoFn) {
  const totalPages = Math.ceil(total / perPage) || 1;
  if (totalPages <= 1 && total <= perPage) {
    // no pagination needed for small result sets
    return;
  }
  const p = document.createElement('div');
  p.className = 'pagination';
  p.innerHTML = `
    <button onclick="${gotoFn}(1)" ${page===1?'disabled':''}>&laquo;</button>
    <button onclick="${gotoFn}(${page-1})" ${page===1?'disabled':''}>&lsaquo; 上一页</button>
    <button class="active">${page} / ${totalPages} (共${total}条)</button>
    <button onclick="${gotoFn}(${page+1})" ${page>=totalPages?'disabled':''}>下一页 &rsaquo;</button>
    <button onclick="${gotoFn}(${totalPages})" ${page>=totalPages?'disabled':''}>&raquo;</button>`;
  container.appendChild(p);
}

// ── Tab switching ────────────────────────────
function switchTab(tab) {
  currentTab = tab;
  // Update buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  // Update panels
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.id === 'panel-' + tab);
  });
  // Load data for the active tab
  if (tab === 'news') {
    loadNewsStatus();
  } else if (tab === 'hotlist') {
    loadHotlistPlatforms();
    loadHotlist();
  } else if (tab === 'rss') {
    loadRSSFeeds();
    loadRSS();
  } else if (tab === 'creator') {
    loadIndustries();
    loadCreatorHotlist();
  } else if (tab === 'chat') {
    initChat();
  }
}

// ── Refresh button (fetch for current tab) ────
async function doRefresh() {
  const btn = document.getElementById('btnRefresh');
  btn.disabled = true;
  btn.classList.add('fetching');
  btn.textContent = '刷新中...';

  try {
    if (currentTab === 'news') {
      const resp = await fetch('/api/news/fetch', {method: 'POST'});
      if (!resp.ok) { const d = await resp.json(); throw new Error(d.error || resp.statusText); }
      const data = await resp.json();
      newsPage = 1;
      loadNewsStatus();
      loadCategories();
      loadNews();
    } else if (currentTab === 'hotlist') {
      const resp = await fetch('/api/hotlist/fetch', {method: 'POST'});
      if (!resp.ok) { const d = await resp.json(); throw new Error(d.error || resp.statusText); }
      await resp.json();
      hotPage = 1;
      loadHotlistPlatforms();
      loadHotlist();
    } else if (currentTab === 'rss') {
      const resp = await fetch('/api/rss/fetch', {method: 'POST'});
      if (!resp.ok) { const d = await resp.json(); throw new Error(d.error || resp.statusText); }
      await resp.json();
      rssPage = 1;
      loadRSSFeeds();
      loadRSS();
    }
  } catch(e) {
    alert('刷新失败: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.classList.remove('fetching');
    btn.textContent = '刷新';
  }
}

// ══════════════════════════════════════════════
// TAB 1: 新闻汇总
// ══════════════════════════════════════════════

// ── Date range slider ────────────────────────
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
    newsPage = 1;
    loadNews();
  }

  thumbL.addEventListener('mousedown', onDown);
  thumbR.addEventListener('mousedown', onDown);
  thumbL.addEventListener('touchstart', onDown, {passive:false});
  thumbR.addEventListener('touchstart', onDown, {passive:false});
  slider.addEventListener('dblclick', () => {
    rangeMin = 0; rangeMax = SLIDER_DAYS;
    render();
    newsPage = 1;
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

function doNewsSearch() {
  newsPage = 1;
  loadNews();
}

// ── Categories ───────────────────────────────
async function loadCategories() {
  try {
    const resp = await fetch('/api/news/categories');
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
  if (activeCategories.has(cat)) activeCategories.delete(cat);
  else activeCategories.add(cat);
  newsPage = 1;
  loadCategories();
  loadNews();
}
function clearCategories() {
  activeCategories.clear();
  newsPage = 1;
  loadCategories();
  loadNews();
}

// ── Sources ──────────────────────────────────
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
  if (activeSources.has(src)) activeSources.delete(src);
  else activeSources.add(src);
  newsPage = 1;
  loadSourceStats();
  loadNews();
}
function clearSources() {
  activeSources.clear();
  newsPage = 1;
  loadSourceStats();
  loadNews();
}

async function loadSourceStats() {
  try {
    const resp = await fetch('/api/news/status');
    const data = await resp.json();
    renderSourceBar(data);
  } catch(e) {}
}

async function loadNewsStatus() {
  try {
    const resp = await fetch('/api/news/status');
    const data = await resp.json();
    renderSourceBar(data);
    document.getElementById('headerMeta').innerHTML =
      '<span>新闻: ' + (data.db_total ?? '-') + ' 条</span>';
  } catch(e) {}
}

// ── Load news ────────────────────────────────
async function loadNews() {
  const keyword = document.getElementById('newsSearchInput').value.trim();
  const semantic = document.getElementById('semanticToggle').checked;

  if (semantic && keyword) {
    await loadSemanticSearch(keyword);
    return;
  }

  const params = new URLSearchParams({ page: newsPage, per_page: PER_PAGE });
  if (keyword) params.set('keyword', keyword);
  if (activeCategories.size > 0) params.set('categories', [...activeCategories].join(','));
  if (activeSources.size > 0) params.set('sources', [...activeSources].join(','));
  const dateFrom = getDateFrom();
  const dateTo = getDateTo();
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);

  try {
    const resp = await fetch('/api/news?' + params);
    const data = await resp.json();
    newsTotal = data.total;
    renderNews(data.items);
  } catch(e) {
    document.getElementById('newsGrid').innerHTML =
      '<div class="empty-state"><div class="icon">&#x26A0;</div><div>加载失败: ' + esc(e.message) + '</div></div>';
  }
}

async function loadSemanticSearch(query) {
  const params = new URLSearchParams({ q: query, n: PER_PAGE });
  if (activeCategories.size > 0) params.set('categories', [...activeCategories].join(','));
  if (activeSources.size > 0) params.set('sources', [...activeSources].join(','));

  const grid = document.getElementById('newsGrid');
  grid.innerHTML = '<div class="empty-state"><div class="icon" style="animation:spin 1s linear infinite">&#x2699;</div><div>正在加载语义搜索模型，请稍候...</div></div>';

  try {
    const resp = await fetch('/api/news/semantic_search?' + params);
    if (!resp.ok) throw new Error(resp.statusText);
    const items = await resp.json();
    if (items.error) throw new Error(items.error);
    newsTotal = items.length;
    renderNews(items, true);
  } catch(e) {
    document.getElementById('semanticToggle').checked = false;
    await loadNews();
    grid.insertAdjacentHTML('afterbegin',
      '<div class="alert alert-warn">语义搜索暂不可用，已切换为关键词搜索</div>');
  }
}

function renderNews(items, showSimilarity = false) {
  const grid = document.getElementById('newsGrid');
  grid.innerHTML = '';
  if (!items || !items.length) {
    grid.innerHTML = '<div class="empty-state"><div class="icon">&#x1F4ED;</div><div>暂无新闻，点击「刷新」启动采集</div></div>';
    return;
  }
  items.forEach(n => {
    const tags = (n.tags||[]).map(t => '<span class="tag">' + esc(t) + '</span>').join('');
    const link = n.url ? '<a class="link" href="' + esc(n.url) + '" target="_blank" rel="noopener">查看原文 &rarr;</a>' : '';
    const ts = n.timestamp ? n.timestamp.replace('T',' ').slice(0,19) : (n.created_at||'').slice(0,19);
    const cats = Array.isArray(n.category) ? n.category : (n.category ? [n.category] : []);
    const catBadges = cats.map(c => '<span class="cat-badge">' + esc(c) + '</span>').join('');
    const simBadge = (showSimilarity && n.similarity !== undefined)
      ? '<span class="similarity-badge">' + (n.similarity*100).toFixed(0) + '%</span>' : '';
    const card = document.createElement('div');
    card.className = 'news-card';
    card.innerHTML =
      '<div class="top-row">' +
        '<span class="source-badge">' + esc(n.source_name) + '</span>' +
        catBadges + simBadge +
        '<span class="timestamp">' + ts + '</span>' +
      '</div>' +
      '<div class="title">' + esc(n.title) + '</div>' +
      '<div class="content">' + esc(n.content) + '</div>' +
      '<div class="bottom-row">' + tags + link + '</div>';
    card.addEventListener('click', () => card.classList.toggle('expanded'));
    grid.appendChild(card);
  });
  renderPagination(grid, newsPage, newsTotal, PER_PAGE, 'gotoNews');
}

function gotoNews(p) {
  newsPage = p;
  loadNews();
  document.getElementById('newsGrid').scrollIntoView({behavior:'smooth',block:'start'});
}

// ══════════════════════════════════════════════
// TAB 2: 热榜
// ══════════════════════════════════════════════

async function loadHotlistPlatforms() {
  try {
    const resp = await fetch('/api/hotlist/platforms');
    hotPlatforms = await resp.json();
    const sel = document.getElementById('hotPlatformSelect');
    // Keep current selection
    const current = sel.value;
    sel.innerHTML = '<option value="">全部平台</option>';
    hotPlatforms.forEach(p => {
      sel.innerHTML += '<option value="' + esc(p.platform) + '">' + esc(p.platform_name) + ' (' + p.count + ')</option>';
    });
    sel.value = current;
  } catch(e) {}
}

async function loadHotlist() {
  const grid = document.getElementById('hotGrid');
  grid.innerHTML = '<div class="loading"><div class="icon" style="animation:spin 1s linear infinite">&#x2699;</div><div>加载中...</div></div>';

  const platform = document.getElementById('hotPlatformSelect').value;
  const hours = document.getElementById('hotHoursSelect').value;

  const params = new URLSearchParams({
    page: hotPage, page_size: PER_PAGE, hours: hours,
  });
  if (platform) params.set('platform', platform);

  try {
    const resp = await fetch('/api/hotlist?' + params);
    const data = await resp.json();
    hotTotal = data.total;
    renderHotlist(data.items);
  } catch(e) {
    grid.innerHTML = '<div class="empty-state"><div class="icon">&#x26A0;</div><div>加载失败: ' + esc(e.message) + '</div></div>';
  }
}

function renderHotlist(items) {
  const grid = document.getElementById('hotGrid');
  grid.innerHTML = '';
  if (!items || !items.length) {
    grid.innerHTML = '<div class="empty-state"><div class="icon">&#x1F4ED;</div><div>暂无热榜数据</div></div>';
    return;
  }
  items.forEach(item => {
    const rank = item.hot_rank || 0;
    let rankClass = '';
    if (rank === 1) rankClass = 'top1';
    else if (rank === 2) rankClass = 'top2';
    else if (rank === 3) rankClass = 'top3';

    const link = item.url ? '<a class="hot-link" href="' + esc(item.url) + '" target="_blank" rel="noopener">查看 &rarr;</a>' : '';
    const crawlTs = item.crawl_time ? item.crawl_time.slice(0,16).replace('T',' ') : '';

    const card = document.createElement('div');
    card.className = 'hot-card';
    card.innerHTML =
      '<div class="hot-rank ' + rankClass + '">' + rank + '</div>' +
      '<div class="hot-info">' +
        '<div class="hot-title">' + esc(item.title) + '</div>' +
        '<div class="hot-meta">' +
          '<span class="hot-platform-badge">' + esc(item.platform_name || item.platform) + '</span>' +
          '<span>热度持续: ' + (item.appear_count || 1) + ' 次</span>' +
          (item.hot_score ? '<span>热度: ' + esc(item.hot_score) + '</span>' : '') +
          '<span>' + crawlTs + '</span>' +
        '</div>' +
      '</div>' +
      link;
    grid.appendChild(card);
  });
  renderPagination(grid, hotPage, hotTotal, PER_PAGE, 'gotoHot');
}

function gotoHot(p) {
  hotPage = p;
  loadHotlist();
  document.getElementById('hotGrid').scrollIntoView({behavior:'smooth',block:'start'});
}

// ══════════════════════════════════════════════
// TAB 3: RSS订阅
// ══════════════════════════════════════════════

async function loadRSSFeeds() {
  try {
    const resp = await fetch('/api/rss/feeds');
    rssFeeds = await resp.json();
    const sel = document.getElementById('rssFeedSelect');
    const current = sel.value;
    sel.innerHTML = '<option value="">全部订阅源</option>';
    rssFeeds.forEach(f => {
      sel.innerHTML += '<option value="' + esc(f.id) + '">' + esc(f.name) + '</option>';
    });
    sel.value = current;
  } catch(e) {}
}

async function loadRSS() {
  const grid = document.getElementById('rssGrid');
  grid.innerHTML = '<div class="loading"><div class="icon" style="animation:spin 1s linear infinite">&#x2699;</div><div>加载中...</div></div>';

  const feedId = document.getElementById('rssFeedSelect').value;
  const keyword = document.getElementById('rssSearchInput').value.trim();
  const params = new URLSearchParams({
    page: rssPage, page_size: PER_PAGE,
  });
  if (feedId) params.set('feed_id', feedId);
  if (keyword) params.set('keyword', keyword);

  try {
    const resp = await fetch('/api/rss/items?' + params);
    const data = await resp.json();
    rssTotal = data.total;
    renderRSS(data.items);
  } catch(e) {
    grid.innerHTML = '<div class="empty-state"><div class="icon">&#x26A0;</div><div>加载失败: ' + esc(e.message) + '</div></div>';
  }
}

function renderRSS(items) {
  const grid = document.getElementById('rssGrid');
  grid.innerHTML = '';
  if (!items || !items.length) {
    grid.innerHTML = '<div class="empty-state"><div class="icon">&#x1F4ED;</div><div>暂无 RSS 条目</div></div>';
    return;
  }

  // Build a feed-name lookup
  const feedMap = {};
  rssFeeds.forEach(f => { feedMap[f.id] = f.name; });

  items.forEach(item => {
    const feedName = feedMap[item.feed_id] || item.feed_id || '';
    const link = item.url ? '<a class="link" href="' + esc(item.url) + '" target="_blank" rel="noopener">查看原文 &rarr;</a>' : '';
    const ts = item.published_at
      ? item.published_at.replace('T',' ').slice(0,16)
      : (item.crawl_time ? item.crawl_time.replace('T',' ').slice(0,16) : '');
    const summary = item.summary || '';

    const card = document.createElement('div');
    card.className = 'rss-card';
    card.innerHTML =
      '<div class="top-row">' +
        '<span class="feed-badge">' + esc(feedName) + '</span>' +
        '<span class="timestamp">' + ts + '</span>' +
        link +
      '</div>' +
      '<div class="title">' + esc(item.title) + '</div>' +
      (summary ? '<div class="summary">' + esc(summary) + '</div>' : '');
    grid.appendChild(card);
  });
  renderPagination(grid, rssPage, rssTotal, PER_PAGE, 'gotoRSS');
}

function gotoRSS(p) {
  rssPage = p;
  loadRSS();
  document.getElementById('rssGrid').scrollIntoView({behavior:'smooth',block:'start'});
}

// ══════════════════════════════════════════════
// RSS Feed Management Modal
// ══════════════════════════════════════════════

function openFeedModal() {
  document.getElementById('feedModal').classList.add('open');
  closeAddForm();
  loadFeedTable();
}

function closeFeedModal() {
  document.getElementById('feedModal').classList.remove('open');
  closeAddForm();
}

function showAddForm() {
  document.getElementById('addFeedForm').classList.add('open');
  document.getElementById('btnShowAddForm').style.display = 'none';
  document.getElementById('newFeedName').value = '';
  document.getElementById('newFeedUrl').value = '';
  document.getElementById('newFeedName').focus();
}

function closeAddForm() {
  document.getElementById('addFeedForm').classList.remove('open');
  document.getElementById('btnShowAddForm').style.display = '';
}

async function loadFeedTable() {
  const tbody = document.getElementById('feedTableBody');
  tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:20px;">加载中...</td></tr>';
  try {
    const resp = await fetch('/api/rss/feeds');
    const feeds = await resp.json();
    rssFeeds = feeds; // keep in sync
    if (!feeds.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:20px;">暂无订阅源</td></tr>';
      return;
    }
    tbody.innerHTML = '';
    feeds.forEach(f => {
      const statusIcon = f.last_error
        ? '<span class="feed-status" title="' + esc(f.last_error) + '" style="color:var(--red);">&#x26A0;</span>'
        : '<span class="feed-status" title="正常" style="color:var(--green);">&#x2713;</span>';
      const lastCrawl = f.last_crawl_time ? f.last_crawl_time.replace('T',' ').slice(0,16) : '-';
      const tr = document.createElement('tr');
      tr.innerHTML =
        '<td><strong>' + esc(f.name) + '</strong><br><span style="font-size:11px;color:var(--muted);">' + lastCrawl + '</span></td>' +
        '<td class="feed-url" title="' + esc(f.url) + '">' + esc(f.url) + '</td>' +
        '<td>' + statusIcon + '</td>' +
        '<td><label class="toggle-switch"><input type="checkbox" ' + (f.enabled ? 'checked' : '') +
          ' onchange="toggleFeedEnabled(\'' + esc(f.id) + '\', this.checked)">' +
          '<span class="toggle-slider"></span></label></td>' +
        '<td><div class="feed-actions">' +
          '<button onclick="editFeed(\'' + esc(f.id) + '\')">编辑</button>' +
          '<button class="btn-del" onclick="deleteFeed(\'' + esc(f.id) + '\')">删除</button>' +
        '</div></td>';
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--red);">加载失败</td></tr>';
  }
}

async function addFeed() {
  const name = document.getElementById('newFeedName').value.trim();
  const url = document.getElementById('newFeedUrl').value.trim();
  if (!name || !url) { alert('名称和 URL 为必填项'); return; }

  const btn = document.getElementById('btnAddFeed');
  btn.disabled = true;
  btn.textContent = '添加中...';

  try {
    // Step 1: Add feed to database
    const resp = await fetch('/api/rss/feeds', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, url: url}),
    });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || '添加失败');

    // Step 2: Auto-fetch to verify the feed works
    btn.textContent = '验证并抓取中...';
    btn.classList.add('fetching');
    const fetchResp = await fetch('/api/rss/fetch', {method: 'POST'});
    const fetchData = await fetchResp.json();
    if (!fetchData.success) {
      // Feed added but fetch failed - still show it in the list
      btn.disabled = false;
      btn.classList.remove('fetching');
      btn.textContent = '添加';
      closeAddForm();
      loadFeedTable();
      loadRSSFeeds();
      alert('订阅源已添加，但首次抓取失败: ' + (fetchData.error || '未知错误'));
      return;
    }

    // Step 3: Refresh UI
    btn.disabled = false;
    btn.classList.remove('fetching');
    btn.textContent = '添加';
    closeAddForm();
    loadFeedTable();
    loadRSSFeeds();
    loadRSS();

    // Brief success feedback
    const totalItems = fetchData.total_items || 0;
    const feedName = name;
    showNotice('success', `${feedName} - 已抓取 ${totalItems} 条内容`);
  } catch(e) {
    btn.disabled = false;
    btn.classList.remove('fetching');
    btn.textContent = '添加';
    alert('添加失败: ' + e.message);
  }
}

async function editFeed(feedId) {
  const feed = rssFeeds.find(f => f.id === feedId);
  if (!feed) return;
  const newName = prompt('编辑订阅源名称:', feed.name);
  if (newName === null) return;
  const trimmedName = newName.trim();
  if (!trimmedName) { alert('名称不能为空'); return; }

  try {
    const resp = await fetch('/api/rss/feeds/' + feedId, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: trimmedName}),
    });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || '更新失败');
    loadFeedTable();
    loadRSSFeeds();
  } catch(e) {
    alert('更新失败: ' + e.message);
  }
}

// ── RSS Discover ──────────────────────────────────

async function discoverFeeds() {
  const url = document.getElementById('discoverUrl').value.trim();
  if (!url) { alert('请输入网站地址'); return; }

  const btn = document.getElementById('btnDiscover');
  const resultDiv = document.getElementById('discoverResult');
  btn.disabled = true;
  btn.textContent = '发现中...';
  resultDiv.style.display = 'none';

  try {
    const resp = await fetch('/api/rss/discover', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: url}),
    });
    const data = await resp.json();

    if (!data.success) {
      let errorHtml = '<div style="color:var(--orange);padding:8px;">' + esc(data.error || '发现失败') + '</div>';
      if (data.generic_available) {
        errorHtml += '<div style="padding:4px 8px;"><a href="#" onclick="document.getElementById(\'customSelectorForm\').style.display=\'block\';return false;" style="color:var(--accent);font-size:12px;">使用自定义 CSS 选择器</a></div>';
      }
      resultDiv.innerHTML = errorHtml;
      resultDiv.style.display = 'block';
      return;
    }

    // Build result cards
    let html = '<div style="color:var(--accent);font-weight:600;margin-bottom:8px;">' + esc(data.site_name) + ' - ' + data.routes.length + ' 个可订阅源</div>';

    // Get existing feeds to check for duplicates
    const feedsResp = await fetch('/api/rss/feeds');
    const existingFeeds = await feedsResp.json();
    const existingUrls = new Set(existingFeeds.map(f => f.url));

    data.routes.forEach(route => {
      const alreadySubscribed = existingUrls.has(route.feed_url);
      const itemsPreview = (route.sample_items || [])
        .map(item => '<div style="font-size:12px;color:var(--muted);padding:2px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(item.title) + '</div>')
        .join('');

      const feedName = data.site_name + '-' + route.name;
      // 使用 data 属性传递参数，避免 onclick 拼接中的引号 XSS 问题
      const subscribeBtn = alreadySubscribed
        ? '<span style="color:var(--green);font-size:12px;">已订阅</span>'
        : (route.error
          ? '<span style="color:var(--red);font-size:12px;">' + esc(route.error) + '</span>'
          : '<button class="btn-add discover-sub-btn" style="padding:3px 12px;font-size:12px;" data-feed-url="' + esc(route.feed_url) + '" data-feed-name="' + esc(feedName) + '">订阅</button>'
        );

      html += '<div style="padding:8px;background:var(--card);border-radius:6px;margin-bottom:6px;border:1px solid var(--border);">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;">' +
          '<div><strong>' + esc(route.name) + '</strong> <span style="color:var(--muted);font-size:12px;">(' + route.item_count + '条)</span></div>' +
          subscribeBtn +
        '</div>' +
        itemsPreview +
      '</div>';
    });

    resultDiv.innerHTML = html;
    resultDiv.style.display = 'block';

  } catch(e) {
    resultDiv.innerHTML = '<div style="color:var(--red);padding:8px;">发现失败: ' + esc(e.message) + '</div>';
    resultDiv.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = '发现';
  }
}

async function subscribeDiscoverRoute(feedUrl, feedName) {
  try {
    const resp = await fetch('/api/rss/feeds', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: feedName, url: feedUrl}),
    });
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || '订阅失败');

    showNotice('success', feedName + ' 订阅成功');
    loadFeedTable();
    loadRSSFeeds();

    // Update the clicked button to show "已订阅"
    const buttons = document.querySelectorAll('#discoverResult .discover-sub-btn');
    buttons.forEach(btn => {
      if (btn.dataset.feedUrl === feedUrl) {
        const span = document.createElement('span');
        span.style.cssText = 'color:var(--green);font-size:12px;';
        span.textContent = '已订阅';
        btn.replaceWith(span);
      }
    });
  } catch(e) {
    alert('订阅失败: ' + e.message);
  }
}

// 事件委托：处理发现区域的订阅按钮点击
document.addEventListener('click', function(e) {
  const btn = e.target.closest('.discover-sub-btn');
  if (btn) {
    subscribeDiscoverRoute(btn.dataset.feedUrl, btn.dataset.feedName);
  }
});

// ── Custom CSS Selector Discover ──────────────────────

async function customDiscover() {
  const url = document.getElementById('discoverUrl').value.trim();
  const itemSelector = document.getElementById('customItemSelector').value.trim();
  const titleSelector = document.getElementById('customTitleSelector').value.trim();
  if (!url || !itemSelector) { alert('请输入网站地址和条目选择器'); return; }

  const resultDiv = document.getElementById('discoverResult');
  resultDiv.innerHTML = '<div style="color:var(--muted);padding:8px;">正在生成...</div>';
  resultDiv.style.display = 'block';

  try {
    const body = { url: url, item_selector: itemSelector };
    if (titleSelector) body.title_selector = titleSelector;

    const resp = await fetch('/api/rss/discover/custom', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await resp.json();

    if (!data.success) {
      resultDiv.innerHTML = '<div style="color:var(--orange);padding:8px;">' + esc(data.error || '生成失败') + '</div>';
      return;
    }

    // Build result cards (same format as discoverFeeds)
    let html = '<div style="color:var(--accent);font-weight:600;margin-bottom:8px;">' + esc(data.site_name) + ' - 自定义源</div>';

    const feedsResp = await fetch('/api/rss/feeds');
    const existingFeeds = await feedsResp.json();
    const existingUrls = new Set(existingFeeds.map(f => f.url));

    data.routes.forEach(route => {
      const alreadySubscribed = existingUrls.has(route.feed_url);
      const itemsPreview = (route.sample_items || [])
        .map(item => '<div style="font-size:12px;color:var(--muted);padding:2px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(item.title) + '</div>')
        .join('');

      const feedName = data.site_name + '-' + route.name;
      const subscribeBtn = alreadySubscribed
        ? '<span style="color:var(--green);font-size:12px;">已订阅</span>'
        : (route.error
          ? '<span style="color:var(--red);font-size:12px;">' + esc(route.error) + '</span>'
          : '<button class="btn-add discover-sub-btn" style="padding:3px 12px;font-size:12px;" data-feed-url="' + esc(route.feed_url) + '" data-feed-name="' + esc(feedName) + '">订阅</button>'
        );

      html += '<div style="padding:8px;background:var(--card);border-radius:6px;margin-bottom:6px;border:1px solid var(--border);">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;">' +
          '<div><strong>' + esc(route.name) + '</strong> <span style="color:var(--muted);font-size:12px;">(' + route.item_count + '条)</span></div>' +
          subscribeBtn +
        '</div>' +
        itemsPreview +
      '</div>';
    });

    resultDiv.innerHTML = html;

  } catch(e) {
    resultDiv.innerHTML = '<div style="color:var(--red);padding:8px;">生成失败: ' + esc(e.message) + '</div>';
  }
}

async function deleteFeed(feedId) {
  if (!confirm('确定删除此订阅源及其所有条目？')) return;
  try {
    const resp = await authFetch('/api/rss/feeds/' + feedId, {method: 'DELETE'});
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || '删除失败');
    loadFeedTable();
    loadRSSFeeds();
  } catch(e) {
    alert('删除失败: ' + e.message);
  }
}

async function toggleFeedEnabled(feedId, enabled) {
  try {
    const resp = await fetch('/api/rss/feeds/' + feedId, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({enabled: enabled ? 1 : 0}),
    });
    const data = await resp.json();
    if (!data.success) {
      // Revert checkbox on failure
      const cb = document.querySelector('input[onchange*="' + feedId + '"]');
      if (cb) cb.checked = !enabled;
      throw new Error(data.error || '更新失败');
    }
  } catch(e) {
    alert('更新失败: ' + e.message);
  }
}

// ══════════════════════════════════════════════
// Initialization
// ══════════════════════════════════════════════

(async function init() {
  // Load global status
  try {
    const resp = await fetch('/api/status');
    const data = await resp.json();
    let metaHtml = '';
    if (data.news && data.news.available) metaHtml += '<span>新闻: ' + data.news.count + ' 条</span>';
    if (data.hotlist && data.hotlist.available) metaHtml += '<span>热榜: ' + (data.hotlist.last_crawl || '-') + '</span>';
    if (data.rss && data.rss.available) metaHtml += '<span>RSS: ' + data.rss.feed_count + ' 源</span>';
    document.getElementById('headerMeta').innerHTML = metaHtml;
  } catch(e) {}

  // Initialize news tab
  initRangeSlider();
  loadNewsStatus();
  loadCategories();
  loadNews();
})();

// ── Toast notification ─────────────────────────
let _toastTimer = null;
function showNotice(type, msg) {
  let el = document.getElementById('toastNotice');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toastNotice';
    el.className = 'toast-notice';
    document.body.appendChild(el);
  }
  el.className = 'toast-notice ' + type;
  el.textContent = msg;
  clearTimeout(_toastTimer);
  requestAnimationFrame(() => { el.classList.add('show'); });
  _toastTimer = setTimeout(() => { el.classList.remove('show'); }, 3000);
}

// ══════════════════════════════════════════════
// TAB 4: 选题创作
// ══════════════════════════════════════════════

let currentFrameworkId = null;
let currentTopicIndustry = '';
let currentTopicKeyword = '';
let topicPollTimer = null;

async function loadIndustries() {
  const sel = document.getElementById('topicIndustry');
  if (sel.options.length > 1) return;
  try {
    const resp = await fetch('/api/topic/industries');
    const industries = await resp.json();
    industries.forEach(ind => {
      const opt = document.createElement('option');
      opt.value = ind; opt.textContent = ind;
      sel.appendChild(opt);
    });
  } catch(e) {
    console.error('加载行业列表失败', e);
  }
}

// ── Creator hotlist browser ──────────────────
let creatorHotPlatforms = [];
let creatorSelectedPlatform = '';

async function loadCreatorHotlist() {
  try {
    const resp = await fetch('/api/hotlist/platforms');
    creatorHotPlatforms = await resp.json();
    if (!creatorHotPlatforms.length) return;
    renderHotlistSidebar();
    // 默认选中第一个
    selectHotPlatform(creatorHotPlatforms[0].platform);
  } catch(e) {
    console.error('加载热榜平台失败', e);
  }
}

function renderHotlistSidebar() {
  const sidebar = document.getElementById('hotlistSidebar');
  sidebar.innerHTML = '';
  creatorHotPlatforms.forEach(p => {
    const div = document.createElement('div');
    div.className = 'hotlist-sidebar-item' + (p.platform === creatorSelectedPlatform ? ' active' : '');
    div.innerHTML = `${esc(p.platform_name)}<span class="count">${esc(String(p.count))}</span>`;
    div.onclick = () => selectHotPlatform(p.platform);
    sidebar.appendChild(div);
  });
}

async function selectHotPlatform(platform) {
  creatorSelectedPlatform = platform;
  // 更新 sidebar 高亮
  document.querySelectorAll('.hotlist-sidebar-item').forEach(el => el.classList.remove('active'));
  const items = document.querySelectorAll('.hotlist-sidebar-item');
  const idx = creatorHotPlatforms.findIndex(p => p.platform === platform);
  if (idx >= 0 && items[idx]) items[idx].classList.add('active');

  // 更新标题
  const name = creatorHotPlatforms.find(p => p.platform === platform)?.platform_name || platform;
  document.getElementById('hotlistHeader').textContent = name + ' 热榜';
  document.getElementById('hotlistItems').innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">加载中...</div>';

  try {
    const resp = await fetch(`/api/hotlist?platform=${encodeURIComponent(platform)}&hours=72&page_size=60`);
    const data = await resp.json();
    renderHotlistItems(data.items || []);
  } catch(e) {
    document.getElementById('hotlistItems').innerHTML = '<div style="color:var(--red);">加载失败</div>';
  }
}

function renderHotlistItems(items) {
  const container = document.getElementById('hotlistItems');
  if (!items.length) {
    container.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center;">暂无数据</div>';
    return;
  }
  container.innerHTML = items.map((item, i) => {
    const rank = item.hot_rank || (i + 1);
    const rankClass = rank <= 3 ? `top${rank}` : 'normal';
    const score = item.hot_score ? `<span class="score">${item.hot_score}</span>` : '';
    return `<div class="hotlist-row">
      <span class="rank ${rankClass}">${rank}</span>
      <span class="title">${item.title}</span>
      ${score}
    </div>`;
  }).join('');
}

async function generateTopics() {
  const industry = document.getElementById('topicIndustry').value;
  const keyword = document.getElementById('topicKeyword').value.trim();
  if (!industry || !keyword) {
    showNotice('err', '请选择行业并输入关键词');
    return;
  }
  currentTopicIndustry = industry;
  currentTopicKeyword = keyword;

  const btn = document.getElementById('btnGenTopic');
  btn.disabled = true; btn.textContent = '生成中...';
  const container = document.getElementById('topicResults');
  container.innerHTML = '<div style="text-align:center;padding:40px;color:var(--muted);"><div class="spinner"></div>正在检索相关素材并生成选题...</div>';

  try {
    const resp = await fetch('/api/topic/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({industry, keyword, top_k: 5})
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || '生成失败');
    }
    const topics = await resp.json();
    renderTopics(topics, container);
  } catch(e) {
    container.innerHTML = `<div class="topic-card"><p style="color:var(--red);">生成失败: ${e.message}</p></div>`;
  } finally {
    btn.disabled = false; btn.textContent = '生成选题';
  }
}

function renderTopics(topics, container) {
  container.innerHTML = '';
  if (!topics.length) {
    container.innerHTML = '<div class="topic-card"><p style="color:var(--muted);">未找到相关素材，请调整关键词重试</p></div>';
    return;
  }
  // 有选题结果时隐藏热榜
  const hb = document.getElementById('hotlistBrowser');
  if (hb) hb.style.display = 'none';
  topics.forEach((t, idx) => {
    const card = document.createElement('div');
    card.className = 'topic-card';
    const sim = t.hotspot.similarity ? ` (相关度 ${Math.round(t.hotspot.similarity * 100)}%)` : '';
    card.innerHTML = `
      <div class="topic-source">${t.hotspot.source || ''} · ${t.hotspot.date || ''}${sim}</div>
      <div style="font-weight:600;font-size:15px;">${t.hotspot.title}</div>
      <div class="topic-summary">${t.hotspot.summary || ''}</div>
      <ul class="title-list">
        ${t.titles.map(title => `<li onclick="selectTitle('${escapeHtml(title)}', '${escapeHtml(t.hotspot.title)}')">${title}</li>`).join('')}
      </ul>
      <div class="topic-explanation">${t.explanation}</div>
    `;
    container.appendChild(card);
  });
}

function escapeHtml(str) {
  return str.replace(/'/g, "\\'").replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function selectTitle(title, sourceTitle) {
  document.getElementById('creatorTopicView').style.display = 'none';
  document.getElementById('creatorFrameworkView').style.display = 'block';
  document.getElementById('articlePanel').style.display = 'none';
  document.getElementById('fwTitle').textContent = title;
  // 展开框架面板
  document.getElementById('fwPanelBody').classList.remove('collapsed');
  document.getElementById('fwToggleIcon').innerHTML = '&#9660;';

  try {
    const resp = await fetch('/api/creator/framework/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: title,
        requirements: '',
        industry: currentTopicIndustry,
        keyword: currentTopicKeyword,
      })
    });
    if (!resp.ok) throw new Error('框架创建失败');
    const fw = await resp.json();
    currentFrameworkId = fw.id;
    renderFramework(fw);
  } catch(e) {
    showNotice('err', '框架创建失败: ' + e.message);
  }
}

function renderFramework(fw) {
  document.getElementById('fwStructure').value = fw.article_structure || '';
  document.getElementById('fwApproach').value = fw.writing_approach || '';
  const chatDiv = document.getElementById('fwChatHistory');
  chatDiv.innerHTML = '';
  (fw.chat_history || []).forEach(msg => {
    const div = document.createElement('div');
    div.className = 'fw-chat-msg';
    const rc = msg.role === 'user' ? 'user' : 'assistant';
    const rn = msg.role === 'user' ? '你' : 'AI';
    div.innerHTML = `<span class="role ${rc}">${rn}:</span>${esc(msg.content)}`;
    chatDiv.appendChild(div);
  });
  chatDiv.scrollTop = chatDiv.scrollHeight;
}

async function saveFrameworkEdit() {
  if (!currentFrameworkId) return;
  const structure = document.getElementById('fwStructure').value.trim();
  const approach = document.getElementById('fwApproach').value.trim();
  try {
    const resp = await fetch(`/api/creator/framework/${currentFrameworkId}/save`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({article_structure: structure, writing_approach: approach})
    });
    if (!resp.ok) throw new Error('保存失败');
    showNotice('ok', '框架已保存');
  } catch(e) {
    showNotice('err', '保存失败: ' + e.message);
  }
}

function toggleFwPanel() {
  const body = document.getElementById('fwPanelBody');
  const icon = document.getElementById('fwToggleIcon');
  body.classList.toggle('collapsed');
  icon.innerHTML = body.classList.contains('collapsed') ? '&#9654;' : '&#9660;';
}

async function sendFrameworkChat(regenerate = false) {
  if (!currentFrameworkId) return;
  const input = document.getElementById('fwChatInput');
  const message = input.value.trim();
  if (!message && !regenerate) return;
  input.value = '';
  try {
    const resp = await fetch(`/api/creator/framework/${currentFrameworkId}/update`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: message || '请重新设计框架', regenerate})
    });
    if (!resp.ok) throw new Error('更新失败');
    const fw = await resp.json();
    renderFramework(fw);
  } catch(e) {
    showNotice('err', '框架更新失败: ' + e.message);
  }
}

function backToTopic() {
  document.getElementById('creatorTopicView').style.display = 'block';
  document.getElementById('creatorFrameworkView').style.display = 'none';
  // 清空选题结果，恢复热榜
  document.getElementById('topicResults').innerHTML = '';
  const hb = document.getElementById('hotlistBrowser');
  if (hb) hb.style.display = 'flex';
  currentFrameworkId = null;
}

// 当前文章原始 markdown
let currentArticleMd = '';
let currentArticleMode = 'preview';

async function confirmAndGenerate() {
  if (!currentFrameworkId) return;
  const btn = document.getElementById('btnGenArticle');
  btn.disabled = true; btn.textContent = '确认中...';
  try {
    await fetch(`/api/creator/framework/${currentFrameworkId}/confirm`, {method: 'POST'});
    const imageCount = parseInt(document.getElementById('imageCount').value);
    const resp = await fetch(`/api/creator/framework/${currentFrameworkId}/generate`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({image_count: imageCount})
    });
    if (!resp.ok) throw new Error('生成启动失败');
    const {task_id} = await resp.json();

    // 收缩框架面板
    document.getElementById('fwPanelBody').classList.add('collapsed');
    document.getElementById('fwToggleIcon').innerHTML = '&#9654;';

    // 显示文章面板
    document.getElementById('articlePanel').style.display = 'block';
    document.getElementById('articleStatus').style.display = 'block';
    document.getElementById('articleStatus').innerHTML = '<div class="spinner"></div><div style="margin-top:12px;">正在生成文章，请稍候...</div>';
    document.getElementById('articlePreview').style.display = 'none';
    document.getElementById('articleEditor').style.display = 'none';
    pollTaskStatus(task_id);
  } catch(e) {
    showNotice('err', e.message);
  } finally {
    btn.disabled = false; btn.textContent = '确认框架并生成文章';
  }
}

function pollTaskStatus(taskId) {
  if (topicPollTimer) clearInterval(topicPollTimer);
  topicPollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/creator/task/${taskId}/status`);
      const task = await resp.json();
      if (task.status === 'completed') {
        clearInterval(topicPollTimer); topicPollTimer = null;
        await showArticleResult(taskId);
      } else if (task.status === 'failed') {
        clearInterval(topicPollTimer); topicPollTimer = null;
        document.getElementById('articleStatus').innerHTML = `<div style="color:var(--red);">生成失败: ${task.progress}</div>`;
      } else {
        document.getElementById('articleStatus').innerHTML = `<div class="spinner"></div><div style="margin-top:12px;">${task.progress}</div>`;
      }
    } catch(e) {
      clearInterval(topicPollTimer); topicPollTimer = null;
    }
  }, 2000);
}

async function showArticleResult(taskId) {
  try {
    const resp = await fetch(`/api/creator/task/${taskId}/result`);
    const result = await resp.json();
    document.getElementById('articleStatus').style.display = 'none';

    let md = result.article || '';

    // 自动将配图插入文章段落中（参考 ms-DYP autoInsertImagesToArticle）
    if (result.images && result.images.length) {
      md = autoInsertImages(md, result.images);
    }

    currentArticleMd = md;
    renderArticlePreview();
    setArticleMode('preview');
  } catch(e) {
    document.getElementById('articleStatus').innerHTML = `<div style="color:var(--red);">加载结果失败: ${e.message}</div>`;
  }
}

function autoInsertImages(md, imageUrls) {
  // 按段落分割
  let paragraphs = md.split(/\n\n+/);
  const count = imageUrls.length;
  if (!count) return md;

  // 计算插入位置：第1张在标题后，其余均匀分布
  const positions = [];
  for (let i = 0; i < count; i++) {
    if (i === 0) {
      positions.push(1); // 标题后
    } else {
      const startIdx = 2;
      const available = paragraphs.length - startIdx;
      const ratio = i / (count - 1 || 1);
      const pos = Math.floor(startIdx + ratio * Math.max(0, available - 1));
      positions.push(Math.min(pos, paragraphs.length - 1));
    }
  }

  // 从后往前插入，避免偏移
  const sorted = positions.map((p, i) => ({pos: p, idx: i})).sort((a, b) => b.pos - a.pos);
  for (const item of sorted) {
    const imgMd = `\n\n![配图${item.idx + 1}](${imageUrls[item.idx]})`;
    paragraphs.splice(item.pos + 1, 0, imgMd.trim());
  }

  return paragraphs.join('\n\n');
}

function renderArticlePreview() {
  const previewDiv = document.getElementById('articlePreview');
  if (typeof marked !== 'undefined') {
    marked.setOptions({ breaks: true, gfm: true });
    previewDiv.innerHTML = safeMarkdown(currentArticleMd);
  } else {
    // fallback 简单渲染
    previewDiv.innerHTML = esc(currentArticleMd)
      .replace(/^# (.+)$/gm, '<h1>$1</h1>')
      .replace(/^## (.+)$/gm, '<h2>$1</h2>')
      .replace(/^### (.+)$/gm, '<h3>$1</h3>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/!\[(.+?)\]\((.+?)\)/g, '<img src="$2" alt="$1">')
      .replace(/\n/g, '<br>');
  }
}

function setArticleMode(mode) {
  currentArticleMode = mode;
  const previewDiv = document.getElementById('articlePreview');
  const editor = document.getElementById('articleEditor');
  const btnP = document.getElementById('btnPreviewMode');
  const btnE = document.getElementById('btnEditMode');

  if (mode === 'preview') {
    previewDiv.style.display = 'block';
    editor.style.display = 'none';
    btnP.style.background = 'var(--accent)'; btnP.style.color = '#fff'; btnP.style.borderColor = 'var(--accent)';
    btnE.style.background = 'var(--card)'; btnE.style.color = 'var(--fg)'; btnE.style.borderColor = 'var(--border)';
    renderArticlePreview();
  } else {
    previewDiv.style.display = 'none';
    editor.style.display = 'block';
    editor.value = currentArticleMd;
    btnE.style.background = 'var(--accent)'; btnE.style.color = '#fff'; btnE.style.borderColor = 'var(--accent)';
    btnP.style.background = 'var(--card)'; btnP.style.color = 'var(--fg)'; btnP.style.borderColor = 'var(--border)';
  }
}

function onArticleEdit() {
  currentArticleMd = document.getElementById('articleEditor').value;
}

// ══════════════════════════════════════════════════
// ── Tab 5: 智能问答 ──────────────────────────────
// ══════════════════════════════════════════════════

let chatSessions = [];
let chatCurrentSessionId = null;
let chatMessages = [];

function handleChatKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
}

async function initChat() {
  await loadChatSessions();
}

async function loadChatSessions() {
  try {
    const resp = await fetch('/api/chat/sessions');
    chatSessions = await resp.json();
    renderChatSidebar();
  } catch(e) { console.error('加载会话列表失败', e); }
}

function renderChatSidebar() {
  const list = document.getElementById('chatSessionList');
  if (!list) return;
  list.innerHTML = chatSessions.map(s => `
    <div class="chat-session-item ${s.id === chatCurrentSessionId ? 'active' : ''}"
         onclick="selectChatSession('${esc(s.id)}')">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div class="chat-session-title">${esc(s.title) || '新对话'}</div>
        <button onclick="deleteChatSession('${esc(s.id)}')" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:12px;padding:2px 4px;" title="删除">&#10005;</button>
      </div>
      <div class="chat-session-meta">${s.msg_count || 0} 条消息</div>
    </div>
  `).join('');
}

async function createNewChat() {
  try {
    const resp = await fetch('/api/chat/sessions', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
    const session = await resp.json();
    chatCurrentSessionId = session.id;
    chatMessages = [];
    renderChatSidebar();
    renderChatMessages();
    document.getElementById('chatInput').focus();
  } catch(e) { console.error('创建会话失败', e); }
}

async function selectChatSession(sessionId) {
  chatCurrentSessionId = sessionId;
  renderChatSidebar();
  await loadChatMessages(sessionId);
}

async function deleteChatSession(sessionId) {
  event.stopPropagation();
  try {
    await fetch(`/api/chat/sessions/${sessionId}`, { method: 'DELETE' });
    if (chatCurrentSessionId === sessionId) {
      chatCurrentSessionId = null;
      chatMessages = [];
      renderChatMessages();
    }
    await loadChatSessions();
  } catch(e) { console.error('删除会话失败', e); }
}

async function loadChatMessages(sessionId) {
  try {
    const resp = await fetch(`/api/chat/sessions/${sessionId}/messages`);
    chatMessages = await resp.json();
    renderChatMessages();
  } catch(e) { console.error('加载消息失败', e); }
}

function renderChatMessages() {
  const container = document.getElementById('chatMessages');
  if (!container) return;

  if (!chatCurrentSessionId) {
    container.innerHTML = '<div class="chat-empty">选择或新建一个对话开始提问</div>';
    return;
  }

  if (chatMessages.length === 0) {
    container.innerHTML = '<div class="chat-empty">输入你的问题，AI 将基于已聚合的信源数据为你解答</div>';
    return;
  }

  container.innerHTML = chatMessages.map(msg => {
    if (msg.role === 'user') {
      return `<div class="chat-msg chat-msg-user"><div class="chat-bubble chat-bubble-user">${escHtml(msg.content)}</div></div>`;
    } else {
      let sourcesHtml = '';
      if (msg.sources) {
        try {
          const sources = JSON.parse(msg.sources);
          if (sources && sources.length > 0) {
            sourcesHtml = '<div class="chat-sources">' + sources.map(s =>
              s.url
                ? `<a class="chat-source-tag" href="${escHtml(s.url)}" target="_blank" title="${escHtml(s.title)}">[${escHtml(s.source)}] ${escHtml(s.title.length > 20 ? s.title.slice(0,20) + '...' : s.title)}</a>`
                : `<span class="chat-source-tag" title="${escHtml(s.title)}">[${escHtml(s.source)}] ${escHtml(s.title.length > 20 ? s.title.slice(0,20) + '...' : s.title)}</span>`
            ).join('') + '</div>';
          }
        } catch(e) {}
      }
      const rendered = safeMarkdown(msg.content);
      return `<div class="chat-msg chat-msg-ai">
        <div class="chat-bubble chat-bubble-ai">${rendered}</div>
        ${sourcesHtml}
      </div>`;
    }
  }).join('');

  container.scrollTop = container.scrollHeight;
}

async function sendChatMessage() {
  const input = document.getElementById('chatInput');
  const question = input.value.trim();
  if (!question || !chatCurrentSessionId) return;

  input.value = '';
  input.disabled = true;

  // 添加用户消息到 UI
  chatMessages.push({ role: 'user', content: question });
  renderChatMessages();

  // 添加空的 AI 消息占位
  chatMessages.push({ role: 'assistant', content: '', sources: '' });
  const aiMsgIndex = chatMessages.length - 1;
  renderChatMessages();

  // 创建打字光标
  const container = document.getElementById('chatMessages');
  const lastBubble = container.querySelector('.chat-msg:last-child .chat-bubble-ai');
  if (lastBubble) lastBubble.innerHTML = '<span class="chat-cursor"></span>';
  container.scrollTop = container.scrollHeight;

  try {
    const resp = await fetch(`/api/chat/sessions/${chatCurrentSessionId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: question }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let fullText = '';
    let sourcesData = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (!data) continue;

        try {
          const event = JSON.parse(data);
          if (event.type === 'content') {
            fullText += event.text;
            if (lastBubble) lastBubble.innerHTML = safeMarkdown(fullText);
            container.scrollTop = container.scrollHeight;
          } else if (event.type === 'sources') {
            sourcesData = JSON.parse(event.data);
          } else if (event.type === 'error') {
            fullText += event.text;
          }
        } catch(e) { /* ignore parse errors */ }
      }
    }

    // 更新消息
    chatMessages[aiMsgIndex].content = fullText;
    chatMessages[aiMsgIndex].sources = sourcesData.length > 0 ? JSON.stringify(sourcesData) : '';
    renderChatMessages();
  } catch(e) {
    chatMessages[aiMsgIndex].content = `请求失败: ${e.message}`;
    renderChatMessages();
  } finally {
    input.disabled = false;
    input.focus();
    loadChatSessions(); // 刷新侧边栏消息计数
  }
}

function escHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

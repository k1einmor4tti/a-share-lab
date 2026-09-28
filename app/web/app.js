const $ = (selector) => document.querySelector(selector);
const state = { selected: null, adjustment: 'qfq', range: '1Y', bars: [], chart: null, searchTimer: null, toastTimer: null };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  if (!response.ok) {
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* Use the status below. */ }
    const detail = typeof payload.detail === 'string' ? payload.detail : `请求失败 (${response.status})`;
    throw new Error(detail);
  }
  return response.json();
}

function toast(message, error = false) {
  const box = $('#toast');
  box.textContent = message;
  box.classList.toggle('error', error);
  box.classList.add('show');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => box.classList.remove('show'), 4200);
}

const format = (value, digits = 2) => value == null ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const integer = (value) => Number(value || 0).toLocaleString('zh-CN');

function renderIndexes(indexes) {
  $('#index-grid').innerHTML = indexes.map((item) => {
    const direction = item.change_pct == null ? 'flat' : item.change_pct >= 0 ? 'positive' : 'negative';
    const change = item.change_pct == null ? '暂无变化' : `${item.change_pct >= 0 ? '+' : ''}${format(item.change_pct)}%`;
    return `<button class="index-card ${state.selected?.code === item.code ? 'selected' : ''}" data-index="${item.code}">
      <div class="index-top"><span class="index-name">${escapeHtml(item.name)}</span><span class="index-code">${escapeHtml(item.code.toUpperCase())}</span></div>
      <div class="index-value">${format(item.close)}</div><div class="index-bottom"><span class="${direction}">${change}</span><span class="index-date">${escapeHtml(item.date || '等待更新')}</span></div></button>`;
  }).join('');
  $('#index-grid').querySelectorAll('[data-index]').forEach((button) => button.addEventListener('click', () => selectIndex(button.dataset.index, button.querySelector('.index-name').textContent)));
}

function renderOverview(data) {
  renderIndexes(data.indexes);
  $('#market-date').textContent = `最近可用收盘日 · ${data.cutoff}`;
  const catalog = data.catalog;
  const total = Number(catalog.total || 0);
  const withBars = Number(catalog.with_bars || 0);
  $('#coverage-count').textContent = integer(withBars);
  $('#catalog-total').textContent = integer(total);
  $('#listed-count').textContent = integer(total - Number(catalog.delisted || 0));
  $('#delisted-count').textContent = integer(catalog.delisted);
  $('#failed-count').textContent = integer(catalog.failed);
  const percent = total ? Math.min(100, Math.round(withBars / total * 100)) : 0;
  $('#coverage-fill').style.width = `${percent}%`;
  $('.progress-track').setAttribute('aria-valuenow', String(percent));

  const job = data.job;
  const chip = $('#job-chip');
  chip.classList.toggle('warn', job?.status === 'partial' || job?.status === 'interrupted');
  const names = { running: '正在更新', completed: '已完成', partial: '部分失败', interrupted: '已中断' };
  chip.textContent = job ? names[job.status] || job.status : '尚未开始';
  const progress = job && job.total ? ` · 进度 ${integer(job.done + job.skipped + job.failed)} / ${integer(job.total)}` : '';
  $('#job-note').textContent = job ? `${job.message || ''}${progress}${job.current_code ? ` · 当前 ${job.current_code}` : ''}` : '首次打开后会在后台建立市场目录并下载历史数据。';
  const failures = job?.failures || [];
  const details = $('#failure-details');
  details.style.display = job?.failure_count ? 'block' : 'none';
  details.querySelector('summary').textContent = `查看最近失败记录（${integer(job?.failure_count)}）`;
  $('#failure-list').innerHTML = failures.length ? failures.map((item) => `<div class="failure-row"><strong>${escapeHtml(item.code)}</strong> · ${escapeHtml(item.error)}</div>`).join('') : '';
  $('#update-button').disabled = job?.status === 'running';
  $('#update-button').innerHTML = job?.status === 'running' ? '<span>◌</span> 正在后台更新' : '<span>↻</span> 更新全市场数据';
}

async function refreshOverview() {
  try { renderOverview(await api('/api/market')); }
  catch (error) { toast(`市场状态读取失败：${error.message}`, true); }
}

async function startUpdate() {
  try {
    const job = await api('/api/update', { method: 'POST' });
    toast(job.already_running ? '已有更新任务正在运行。' : '已在后台启动全市场更新。');
    await refreshOverview();
  } catch (error) { toast(error.message, true); }
}

function renderResults(items) {
  $('#results-count').textContent = `${items.length} 条`;
  $('#stock-results').innerHTML = items.length ? items.map((item) => `<button class="result-item ${state.selected?.code === item.code ? 'active' : ''}" data-code="${escapeHtml(item.code)}">
    <span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.code)} · ${item.bar_count ? `${integer(item.bar_count)} 根日线` : '尚无本地日线'}</small></span>
    <span class="tag ${item.status === 'delisted' ? 'delisted' : ''}">${item.status === 'delisted' ? '已退市' : '在市'}</span></button>`).join('') : '<div class="empty-message">没有找到匹配的股票。</div>';
  $('#stock-results').querySelectorAll('[data-code]').forEach((button) => button.addEventListener('click', () => selectStock(button.dataset.code)));
}

async function searchStocks() {
  const query = $('#stock-search').value.trim();
  if (!query) { $('#results-count').textContent = '—'; $('#stock-results').innerHTML = '<div class="empty-message">输入代码或名称开始搜索。</div>'; return; }
  try { renderResults((await api(`/api/stocks?q=${encodeURIComponent(query)}`)).items); }
  catch (error) { toast(`搜索失败：${error.message}`, true); }
}

async function selectStock(code) {
  state.selected = { type: 'stock', code };
  state.adjustment = 'qfq';
  state.range = '1Y';
  await loadSelected();
  searchStocks();
  refreshOverview();
}

async function selectIndex(code, name) {
  state.selected = { type: 'index', code, name };
  state.range = '1Y';
  await loadSelected();
  refreshOverview();
  $('#stock-explorer').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function loadSelected() {
  const selection = state.selected;
  if (!selection) return;
  $('#chart-side').innerHTML = '<div class="empty-chart">正在读取历史日线…</div>';
  try {
    const path = selection.type === 'stock' ? `/api/stocks/${selection.code}/bars?adjustment=${state.adjustment}` : `/api/indexes/${selection.code}/bars`;
    const payload = await api(path);
    if (state.selected?.code !== selection.code) return;
    state.bars = payload.bars;
    renderDetail(payload);
  } catch (error) { $('#chart-side').innerHTML = `<div class="empty-chart">${escapeHtml(error.message)}</div>`; toast(error.message, true); }
}

function renderDetail(payload) {
  const isStock = state.selected.type === 'stock';
  const symbol = payload.symbol || { code: payload.code, name: payload.name, status: 'listed' };
  const bars = payload.bars;
  const sources = [...new Set(bars.map((bar) => bar.source).filter(Boolean))];
  const latest = bars.at(-1);
  const availableFirst = state.adjustment === 'raw' ? symbol.raw_first : symbol.adjusted_first;
  const availableLast = state.adjustment === 'raw' ? symbol.raw_last : symbol.adjusted_last;
  const missing = payload.unverified_ranges || [];
  const missingLabel = missing.length ? missing.slice(0, 4).map((range) => `${escapeHtml(range.start)}—${escapeHtml(range.end)}`).join('、') + (missing.length > 4 ? ` 等 ${missing.length} 段` : '') : '无未验证区间';
  const detail = $('#chart-side');
  detail.innerHTML = `<div class="detail-heading"><div><h3>${escapeHtml(symbol.name)}</h3><p>${escapeHtml(symbol.code)} · ${isStock ? escapeHtml(symbol.exchange) + ' · 日线' : '指数 · 日线'}</p></div>
    <span class="detail-status ${symbol.status === 'delisted' ? 'delisted' : ''}">${symbol.status === 'delisted' ? '已退市' : '本地历史'}</span></div>
    ${isStock ? `<div class="detail-actions"><button id="detail-backtest" class="text-button">使用这只股票回测 ↗</button>${!bars.length ? '<button id="detail-priority" class="text-button">优先下载此股 ↻</button>' : ''}</div>` : ''}
    <div class="detail-meta"><span>最新收盘<strong>${format(latest?.close)}</strong></span><span>日期<strong>${escapeHtml(latest?.date || '—')}</strong></span><span>总根数<strong>${integer(payload.total_bars)}</strong></span></div>
    ${isStock ? `<div class="coverage-detail"><strong>可用行情</strong><span>${escapeHtml(availableFirst || '—')} — ${escapeHtml(availableLast || '—')}</span><strong>未验证区间</strong><span>${missingLabel}</span></div>` : ''}
    <div class="chart-toolbar"><div class="segmented" id="range-switch"><button data-range="1Y">近 1 年</button><button data-range="5Y">近 5 年</button><button data-range="ALL">全部</button></div>
    ${isStock ? '<div class="segmented" id="adjust-switch"><button data-adjust="qfq">前复权</button><button data-adjust="raw">未复权</button></div>' : ''}</div>
    <div class="chart-wrap"><canvas id="price-chart" aria-label="历史收盘价折线图"></canvas><div class="chart-tooltip" id="chart-tooltip"></div></div>
    <div class="chart-foot"><span id="chart-range-label">—</span><span>来源：${escapeHtml(sources.join(' / ') || '暂无数据')}</span></div>
    ${!bars.length ? '<div class="empty-message">当前没有可显示的日线。全市场更新正在后台进行；失败记录可在上方查看。</div>' : ''}`;
  detail.querySelectorAll('[data-range]').forEach((button) => button.addEventListener('click', () => { state.range = button.dataset.range; updateSegments(); drawChart(); }));
  detail.querySelectorAll('[data-adjust]').forEach((button) => button.addEventListener('click', () => { state.adjustment = button.dataset.adjust; loadSelected(); }));
  if (isStock) {
    $('#detail-backtest').addEventListener('click', () => { $('#bt-code').value = symbol.code; showView('backtest'); });
    if ($('#detail-priority')) $('#detail-priority').addEventListener('click', async () => {
      try { await api(`/api/stocks/${symbol.code}/sync`, { method: 'POST' }); toast(`${symbol.code} 已加入后台优先队列。`); refreshOverview(); }
      catch (error) { toast(error.message, true); }
    });
  }
  updateSegments();
  drawChart();
}

function updateSegments() {
  document.querySelectorAll('[data-range]').forEach((button) => button.classList.toggle('active', button.dataset.range === state.range));
  document.querySelectorAll('[data-adjust]').forEach((button) => button.classList.toggle('active', button.dataset.adjust === state.adjustment));
}

function visibleBars() {
  if (!state.bars.length || state.range === 'ALL') return state.bars;
  const end = new Date(`${state.bars.at(-1).date}T00:00:00`);
  const first = new Date(end);
  first.setFullYear(first.getFullYear() - (state.range === '1Y' ? 1 : 5));
  return state.bars.filter((bar) => new Date(`${bar.date}T00:00:00`) >= first);
}

function drawChart() {
  const canvas = $('#price-chart');
  if (!canvas) return;
  const bars = visibleBars();
  const container = canvas.parentElement;
  const rect = container.getBoundingClientRect();
  const width = Math.max(240, rect.width), height = Math.max(180, rect.height);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);
  const foot = $('#chart-range-label');
  if (!bars.length) { foot.textContent = '无可用数据'; return; }
  foot.textContent = `${bars[0].date} — ${bars.at(-1).date} · ${bars.length} 根日线`;
  const pad = { left: 12, right: 58, top: 23, bottom: 28 };
  const plotWidth = width - pad.left - pad.right, plotHeight = height - pad.top - pad.bottom;
  const values = bars.map((bar) => Number(bar.close));
  const minimum = Math.min(...values), maximum = Math.max(...values);
  const span = maximum - minimum || 1;
  const low = minimum - span * .08, high = maximum + span * .08;
  const point = (index) => ({ x: pad.left + (bars.length === 1 ? 0 : index / (bars.length - 1) * plotWidth), y: pad.top + (high - values[index]) / (high - low) * plotHeight });
  ctx.strokeStyle = '#29404b'; ctx.fillStyle = '#718a95'; ctx.lineWidth = 1; ctx.font = '10px system-ui';
  for (let line = 0; line <= 4; line++) {
    const y = pad.top + line * plotHeight / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right + 4, y); ctx.stroke();
    ctx.fillText(format(high - line * (high - low) / 4), width - pad.right + 11, y + 3);
  }
  ctx.fillText(bars[0].date.slice(0, 7), pad.left, height - 8);
  ctx.fillText(bars.at(-1).date.slice(0, 7), width - pad.right - 36, height - 8);
  const gradient = ctx.createLinearGradient(0, pad.top, 0, height - pad.bottom);
  gradient.addColorStop(0, '#b8ee9150'); gradient.addColorStop(1, '#b8ee9104');
  ctx.beginPath(); bars.forEach((_, index) => { const p = point(index); index ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y); });
  ctx.lineTo(point(bars.length - 1).x, height - pad.bottom); ctx.lineTo(point(0).x, height - pad.bottom); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
  ctx.beginPath(); bars.forEach((_, index) => { const p = point(index); index ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y); });
  ctx.strokeStyle = '#caeb91'; ctx.lineWidth = 2; ctx.stroke();
  state.chart = { bars, point, width, height, pad };
  canvas.onmousemove = (event) => {
    const x = event.clientX - canvas.getBoundingClientRect().left;
    const index = Math.max(0, Math.min(bars.length - 1, Math.round((x - pad.left) / plotWidth * (bars.length - 1))));
    const item = bars[index], p = point(index), tooltip = $('#chart-tooltip');
    tooltip.innerHTML = `<strong>${escapeHtml(item.date)}</strong><br>收盘 ${format(item.close)}<br>开盘 ${format(item.open)} · 最高 ${format(item.high)} · 最低 ${format(item.low)}`;
    tooltip.style.display = 'block'; tooltip.style.left = `${Math.min(width - 160, Math.max(5, p.x + 10))}px`; tooltip.style.top = `${Math.max(4, p.y - 65)}px`;
  };
  canvas.onmouseleave = () => { const tooltip = $('#chart-tooltip'); if (tooltip) tooltip.style.display = 'none'; };
}

function showView(name) {
  const labels = { market: '市场总览', backtest: '策略回测', assistant: '策略助手' };
  document.querySelectorAll('.view').forEach((view) => view.classList.toggle('active', view.id === `view-${name}`));
  document.querySelectorAll('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === name));
  $('#page-name').textContent = labels[name];
  if (name === 'market') requestAnimationFrame(drawChart);
}

document.querySelectorAll('.nav-item').forEach((item) => item.addEventListener('click', () => showView(item.dataset.view)));
$('#update-button').addEventListener('click', startUpdate);
$('#jump-search').addEventListener('click', () => { $('#stock-explorer').scrollIntoView({ behavior: 'smooth' }); $('#stock-search').focus({ preventScroll: true }); });
$('#stock-search').addEventListener('input', () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(searchStocks, 220); });
$('#stock-search').addEventListener('keydown', (event) => { if (event.key === 'Enter') { clearTimeout(state.searchTimer); searchStocks(); } });
window.addEventListener('resize', () => requestAnimationFrame(drawChart));
refreshOverview();
setInterval(refreshOverview, 5000);

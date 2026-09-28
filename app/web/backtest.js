const backtestState = { modules: [], selected: 'buy_hold', result: null, compared: [] };

function backtestLayout() {
  $('#backtest-root').classList.remove('coming-soon');
  $('#backtest-root').innerHTML = `<div class="panel-heading"><div><p class="eyebrow">NEW RUN</p><h2>创建单股回测</h2></div><span class="muted">信号收盘后生成 · 下一交易日成交</span></div>
    <div class="backtest-grid"><div class="backtest-form">
      <label class="field-label">股票代码<input id="bt-code" inputmode="numeric" maxlength="6" placeholder="例如 600000"></label>
      <div class="field-label">策略模块</div><div class="strategy-grid" id="strategy-grid"></div>
      <div id="strategy-params" class="parameter-grid"></div>
      <div class="date-grid"><label class="field-label">开始日期（可选）<input id="bt-start" type="date"></label><label class="field-label">结束日期（可选）<input id="bt-end" type="date"></label></div>
      <details class="advanced-settings"><summary>交易设置与费用</summary><div id="execution-fields" class="parameter-grid"></div><p>费率对整个回测区间固定；公司行动、停牌和涨跌停处理在结果中标明近似范围。</p></details>
      <div class="backtest-actions"><button id="run-backtest" class="primary-button">运行回测 <span>↗</span></button><button id="bt-priority" class="secondary-button">优先下载此股</button></div>
      <p class="inline-message" id="bt-message"></p>
    </div><div class="backtest-result" id="bt-result"><div class="empty-chart"><div class="empty-symbol">⌁</div><strong>等待一次回测</strong><span>选择策略并输入股票代码；结果、收益曲线和订单将在此显示。</span></div></div></div>
    <div class="history-section"><div class="section-heading"><div><p class="eyebrow">SAVED RUNS</p><h2>历史回测</h2></div><span class="muted">结果保存在本机，可重新打开或下载</span></div><div id="bt-history" class="history-list"></div><div id="bt-comparison"></div></div>`;
}

function renderStrategyModules() {
  $('#strategy-grid').innerHTML = backtestState.modules.map((module) => `<button class="strategy-card ${module.key === backtestState.selected ? 'active' : ''}" data-strategy="${escapeHtml(module.key)}"><span class="strategy-check">${module.key === backtestState.selected ? '✓' : '+'}</span><strong>${escapeHtml(module.name)}</strong><small>${escapeHtml(module.description)}</small></button>`).join('');
  document.querySelectorAll('[data-strategy]').forEach((button) => button.addEventListener('click', () => {
    backtestState.selected = button.dataset.strategy; renderStrategyModules(); renderStrategyParams();
  }));
}

function renderStrategyParams() {
  const module = backtestState.modules.find((item) => item.key === backtestState.selected);
  $('#strategy-params').innerHTML = module.parameters.length ? module.parameters.map((param) => `<label class="field-label">${escapeHtml(param.label)}<input data-param="${escapeHtml(param.key)}" type="number" min="${param.min}" max="${param.max}" step="${param.type === 'integer' ? '1' : '0.1'}" value="${param.default}"></label>`).join('') : '<p class="no-params">该策略没有额外参数。</p>';
}

function renderExecution(defaults) {
  const labels = { initial_cash: '初始资金（元）', allocation: '目标资金比例', commission_rate: '佣金率', stamp_tax_rate: '卖出印花税率', transfer_fee_rate: '过户费率', min_commission: '最低佣金（元）', slippage_rate: '滑点率' };
  $('#execution-fields').innerHTML = Object.entries(defaults).map(([key, value]) => `<label class="field-label">${escapeHtml(labels[key] || key)}<input data-execution="${escapeHtml(key)}" type="number" min="0" step="any" value="${value}"></label>`).join('');
}

function backtestPayload() {
  const code = $('#bt-code').value.trim();
  if (!/^\d{6}$/.test(code)) throw new Error('请输入六位股票代码。');
  const params = {}, execution = {};
  document.querySelectorAll('[data-param]').forEach((input) => { params[input.dataset.param] = Number(input.value); });
  document.querySelectorAll('[data-execution]').forEach((input) => { execution[input.dataset.execution] = Number(input.value); });
  return { code, strategy: backtestState.selected, params, execution,
    start: $('#bt-start').value || null, end: $('#bt-end').value || null };
}

async function runBacktest() {
  const button = $('#run-backtest'), message = $('#bt-message');
  try {
    const payload = backtestPayload();
    button.disabled = true; button.textContent = '正在运行…'; message.textContent = '';
    const report = await api('/api/backtests', { method: 'POST', body: JSON.stringify(payload) });
    backtestState.result = report;
    renderBacktestResult(report);
    await loadBacktestHistory();
    toast(`${report.name} · ${report.strategy_name} 回测已保存。`);
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { button.disabled = false; button.innerHTML = '运行回测 <span>↗</span>'; }
}

async function prioritizeForBacktest() {
  const code = $('#bt-code').value.trim();
  if (!/^\d{6}$/.test(code)) return toast('先输入六位股票代码。', true);
  try {
    const result = await api(`/api/stocks/${code}/sync`, { method: 'POST' });
    toast(`${code} 已加入后台优先队列；任务 ${result.id.slice(0, 8)}。`);
    $('#bt-message').textContent = '股票已排入优先下载。完成后即可运行回测。';
  } catch (error) { toast(error.message, true); }
}

function metric(label, value, unit = '%', tone = '') {
  return `<div class="metric-card"><span>${label}</span><strong class="${tone}">${value == null ? '—' : `${format(value)}${unit}`}</strong></div>`;
}

function renderBacktestResult(report) {
  const m = report.metrics;
  const positive = (value) => value >= 0 ? 'positive' : 'negative';
  const orderRows = report.orders.slice(0, 40).map((order) => `<tr><td>${escapeHtml((order.updated_at || order.created_at || '').slice(0, 10))}</td><td class="${order.side === 'buy' ? 'positive' : 'negative'}">${order.side === 'buy' ? '买入' : '卖出'}</td><td>${format(order.filled_quantity, 0)}</td><td>${format(order.avg_price)}</td><td>${escapeHtml(order.status)}</td></tr>`).join('');
  $('#bt-result').innerHTML = `<div class="result-header"><div><p class="eyebrow">BACKTEST RESULT</p><h2>${escapeHtml(report.name)} <span>${escapeHtml(report.code)}</span></h2><p>${escapeHtml(report.strategy_name)} · ${escapeHtml(report.actual_start)} — ${escapeHtml(report.actual_end)}</p></div><a class="secondary-button" href="/api/backtests/${encodeURIComponent(report.id)}/export">下载报告 ↧</a></div>
    <div class="metric-grid">${metric('策略收益', m.total_return_pct, '%', positive(m.total_return_pct))}${metric('沪深300同期', m.benchmark_return_pct, '%', positive(m.benchmark_return_pct))}${metric('年化收益', Number(m.annualized_return) * 100, '%', positive(m.annualized_return))}${metric('最大回撤', m.max_drawdown_pct, '%')}${metric('夏普比率', m.sharpe_ratio, '')}${metric('成交次数', m.execution_count, '', '')}</div>
    <div class="result-section-title">资金曲线 <span><i class="legend-line strategy"></i>策略 <i class="legend-line benchmark"></i>沪深300</span></div><div class="equity-chart"><canvas id="equity-canvas" aria-label="策略和沪深300资金曲线"></canvas></div>
    <div class="result-section-title">成交与订单 <span>${report.orders.length} 条订单</span></div><div class="table-scroll"><table class="orders-table"><thead><tr><th>日期</th><th>方向</th><th>成交数量</th><th>成交价格</th><th>状态</th></tr></thead><tbody>${orderRows || '<tr><td colspan="5">该区间没有成交订单</td></tr>'}</tbody></table></div>
    <details class="assumptions"><summary>数据、执行规则与近似范围</summary><ul>${report.assumptions.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul><p>信号与行情来源：${escapeHtml(report.data_sources.join(' / '))} · 快照 SHA-256 已包含在下载报告中。</p></details>`;
  requestAnimationFrame(() => drawEquityChart(report));
}

function drawEquityChart(report) {
  const canvas = $('#equity-canvas'); if (!canvas) return;
  const width = Math.max(260, canvas.parentElement.clientWidth), height = 230, ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio; canvas.height = height * ratio; canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
  const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
  const series = [report.equity, report.benchmark_equity];
  const values = series.flatMap((items) => items.map((item) => item.value));
  if (!values.length) return;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pad = { left: 12, right: 63, top: 18, bottom: 25 }, plotWidth = width - pad.left - pad.right, plotHeight = height - pad.top - pad.bottom;
  ctx.font = '10px system-ui'; ctx.strokeStyle = '#2a404a'; ctx.fillStyle = '#8097a0'; ctx.lineWidth = 1;
  for (let row = 0; row <= 4; row++) { const y = pad.top + row * plotHeight / 4; ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke(); ctx.fillText(format(max - row * span / 4, 0), width - pad.right + 8, y + 3); }
  series.forEach((items, which) => {
    ctx.beginPath(); items.forEach((item, index) => { const x = pad.left + (items.length === 1 ? 0 : index / (items.length - 1) * plotWidth), y = pad.top + (max - item.value) / span * plotHeight; index ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.strokeStyle = which ? '#75c9bd' : '#d7f475'; ctx.lineWidth = 2; ctx.stroke();
  });
  ctx.fillStyle = '#8097a0'; ctx.fillText(report.equity[0].date.slice(0, 7), pad.left, height - 6); ctx.fillText(report.equity.at(-1).date.slice(0, 7), width - pad.right - 38, height - 6);
}

async function loadBacktestHistory() {
  try {
    const items = (await api('/api/backtests')).items;
    $('#bt-history').innerHTML = items.length ? items.map((item) => `<div class="history-item"><div><strong>${escapeHtml(item.code)}</strong><span>${escapeHtml(item.strategy)} · ${escapeHtml(item.created_at.slice(0, 16))}</span></div><div><button data-open-run="${escapeHtml(item.id)}">打开</button><button data-compare-run="${escapeHtml(item.id)}">对比</button></div></div>`).join('') : '<div class="empty-message">还没有保存的回测。</div>';
    document.querySelectorAll('[data-open-run]').forEach((button) => button.addEventListener('click', () => openBacktest(button.dataset.openRun)));
    document.querySelectorAll('[data-compare-run]').forEach((button) => button.addEventListener('click', () => compareBacktest(button.dataset.compareRun)));
  } catch (error) { $('#bt-history').innerHTML = `<div class="empty-message">${escapeHtml(error.message)}</div>`; }
}

async function openBacktest(id) {
  try { const report = await api(`/api/backtests/${encodeURIComponent(id)}`); backtestState.result = report; renderBacktestResult(report); $('#bt-result').scrollIntoView({behavior: 'smooth'}); }
  catch (error) { toast(error.message, true); }
}

async function compareBacktest(id) {
  try {
    const report = await api(`/api/backtests/${encodeURIComponent(id)}`);
    backtestState.compared = [...backtestState.compared.filter((item) => item.id !== id), report].slice(-3);
    const rows = backtestState.compared.map((item) => `<tr><td>${escapeHtml(item.code)} · ${escapeHtml(item.strategy_name)}</td><td>${escapeHtml(item.actual_start)}—${escapeHtml(item.actual_end)}</td><td>${format(item.metrics.total_return_pct)}%</td><td>${format(item.metrics.benchmark_return_pct)}%</td><td>${format(item.metrics.max_drawdown_pct)}%</td></tr>`).join('');
    $('#bt-comparison').innerHTML = `<div class="result-section-title">已选结果对比 <button id="clear-comparison" class="text-button">清空</button></div><div class="table-scroll"><table class="orders-table"><thead><tr><th>股票 · 策略</th><th>区间</th><th>策略收益</th><th>基准收益</th><th>最大回撤</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    $('#clear-comparison').addEventListener('click', () => { backtestState.compared = []; $('#bt-comparison').innerHTML = ''; });
  } catch (error) { toast(error.message, true); }
}

async function initializeBacktests() {
  backtestLayout();
  try {
    const payload = await api('/api/strategies');
    backtestState.modules = payload.modules;
    renderStrategyModules(); renderStrategyParams(); renderExecution(payload.execution_defaults);
  } catch (error) { $('#bt-message').textContent = error.message; }
  $('#run-backtest').addEventListener('click', runBacktest);
  $('#bt-priority').addEventListener('click', prioritizeForBacktest);
  loadBacktestHistory();
}

window.addEventListener('resize', () => { if (backtestState.result && $('#equity-canvas')) drawEquityChart(backtestState.result); });
initializeBacktests();

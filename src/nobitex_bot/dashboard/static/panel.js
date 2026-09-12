// پنل معاملات کاغذی — داده از /api/overview (هر ۱۰ ثانیه) و /api/candles (هر ۲۰ ثانیه).
// مبالغ در API به ریال‌اند و این‌جا به تومان نمایش داده می‌شوند؛ قیمت بازار ریالی هم به تومان.
(() => {
  'use strict';
  const LWC = window.LightweightCharts;
  const root = document.getElementById('panel');
  const css = getComputedStyle(root);
  const SERIES_VAR = { loose: '--series-loose', strict: '--series-strict', tuned: '--series-tuned' };
  const GOOD = '#0ca30c', CRITICAL = '#d03b3b', NEUTRAL = '#8b93a7', SURFACE = '#12151d';
  const RES_SEC = { '5': 300, '15': 900, '30': 1800, '60': 3600, '180': 10800, '240': 14400 };

  const colorOf = (p) => css.getPropertyValue(SERIES_VAR[p.profile] || '--series-loose').trim();
  const dashed = (p) => (p.portfolio_direction || p.direction) === 'both';
  const nf = (digits) => new Intl.NumberFormat('fa-IR', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
  const fa0 = nf(0), fa2 = nf(2);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const toman = (rial) => (rial == null ? '—' : fa0.format(rial / 10));
  const signed = (text, v) => (v > 0 ? '+' : '') + text;
  const pct = (ratio, digits = 2) =>
    ratio == null ? '—' : signed(new Intl.NumberFormat('fa-IR', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(ratio * 100), ratio) + '٪';
  const cls = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat');
  const isIrt = (symbol) => symbol.endsWith('IRT');
  const displayPrice = (symbol, v) => (v == null ? null : isIrt(symbol) ? v / 10 : v);
  const priceText = (symbol, v) => {
    const x = displayPrice(symbol, v);
    if (x == null) return '—';
    return nf(Math.abs(x) >= 1000 ? 0 : Math.abs(x) >= 1 ? 2 : 6).format(x);
  };
  const symbolText = (s) => s.replace(/(IRT|USDT)$/, '/$1');
  const dateTime = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { timeZone: 'Asia/Tehran', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  const hourMinute = new Intl.DateTimeFormat('fa-IR', { timeZone: 'Asia/Tehran', hour: '2-digit', minute: '2-digit' });
  const dayMonth = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { timeZone: 'Asia/Tehran', month: 'short', day: 'numeric' });
  const timeText = (ts) => (ts ? dateTime.format(new Date(ts * 1000)) : '—');
  const durationText = (seconds) => {
    const m = Math.max(0, Math.round(seconds / 60));
    if (m < 60) return fa0.format(m) + ' دقیقه';
    const h = Math.floor(m / 60);
    return h < 48 ? `${fa0.format(h)} ساعت ${fa0.format(m % 60)} دقیقه` : `${fa0.format(Math.floor(h / 24))} روز`;
  };
  const keyHtml = (p) => `<span class="key ${dashed(p) ? 'dashed' : ''}" style="--c:${colorOf(p)}"></span>`;
  const dirBadge = (d) => (d === 'buy' ? '<span class="badge success">خرید</span>' : '<span class="badge danger">فروش</span>');

  let data = null;
  let filter = 'all';
  let liveSymbol = null, liveRes = null, userPicked = false, lastBar = null;

  // ---------------------------------------------------------------- نمودارها

  const makeChart = (el, priceFormatter) =>
    LWC.createChart(el, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: NEUTRAL, fontFamily: 'Vazirmatn, Tahoma, sans-serif' },
      grid: { vertLines: { color: 'rgba(35,40,56,.55)' }, horzLines: { color: 'rgba(35,40,56,.55)' } },
      rightPriceScale: { borderColor: '#232838' },
      timeScale: {
        borderColor: '#232838', timeVisible: true, secondsVisible: false,
        tickMarkFormatter: (t, type) => (type >= 3 ? hourMinute : dayMonth).format(new Date(t * 1000)),
      },
      localization: { locale: 'fa-IR', timeFormatter: timeText, ...(priceFormatter ? { priceFormatter } : {}) },
      crosshair: { mode: 0 },
    });

  const equityEl = document.getElementById('equity-chart');
  const equityChart = makeChart(equityEl, (v) => fa2.format(v) + '٪');
  const equitySeries = new Map();
  let zeroLine = null;

  const tip = document.getElementById('equity-tip');
  equityChart.subscribeCrosshairMove((param) => {
    if (!data || !param.time || !param.point) { tip.style.display = 'none'; return; }
    const rows = data.portfolios.map((p) => {
      const point = param.seriesData.get(equitySeries.get(p.label));
      return point ? `<div class="row">${keyHtml(p)}${esc(p.title)}<b>${pct(point.value / 100)}</b></div>` : '';
    }).join('');
    if (!rows) { tip.style.display = 'none'; return; }
    tip.innerHTML = `<div class="muted">${timeText(param.time)}</div>${rows}`;
    tip.style.display = 'block';
    const width = tip.offsetWidth;
    tip.style.left = (param.point.x + 18 + width > equityEl.clientWidth ? param.point.x - width - 18 : param.point.x + 18) + 'px';
  });

  const liveEl = document.getElementById('live-chart');
  const liveChart = makeChart(liveEl);
  const candles = liveChart.addCandlestickSeries({
    upColor: GOOD, downColor: CRITICAL, wickUpColor: GOOD, wickDownColor: CRITICAL, borderVisible: false,
  });
  let priceLines = [];

  // ---------------------------------------------------------------- رندر

  function pulse(el, ageSeconds, okBelow, slowBelow) {
    if (ageSeconds == null) { el.innerHTML = '<span class="pulse bad"><i></i>بدون داده</span>'; return; }
    const state = ageSeconds <= okBelow ? ['good', 'زنده'] : ageSeconds <= slowBelow ? ['warn', 'کند'] : ['bad', 'قطع'];
    el.innerHTML = `<span class="pulse ${state[0]}" title="${durationText(ageSeconds)} پیش"><i></i>${state[1]}</span>`;
  }

  function renderHero() {
    const initial = data.portfolios.reduce((s, p) => s + p.initial_capital, 0);
    const equity = data.portfolios.reduce((s, p) => s + p.equity, 0);
    document.getElementById('hero-value').textContent = toman(equity);
    const delta = document.getElementById('hero-delta');
    const ratio = initial ? (equity - initial) / initial : 0;
    delta.className = 'delta ' + cls(ratio);
    delta.textContent = `${pct(ratio)} (${signed(toman(equity - initial), equity - initial)} تومان)`;
    document.getElementById('tile-open').textContent = fa0.format(data.open_positions.length);
    document.getElementById('tile-closed').textContent = fa0.format(data.portfolios.reduce((s, p) => s + p.closed_count, 0));
    pulse(document.getElementById('tile-bot'), data.status_updated_at ? data.now - data.status_updated_at : null, 300, 1200);
    pulse(document.getElementById('tile-prices'), data.prices_updated_at ? data.now - data.prices_updated_at : null, 60, 300);
  }

  function spark(p) {
    const pts = p.curve;
    if (pts.length < 2) return '<svg class="spark"></svg>';
    const W = 300, H = 46;
    const x0 = pts[0][0], x1 = pts[pts.length - 1][0];
    const ys = pts.map((q) => q[1]);
    const lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
    const sx = (t) => ((t - x0) / (x1 - x0 || 1)) * W;
    const sy = (v) => H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6);
    const d = pts.map((q, i) => `${i ? 'L' : 'M'}${sx(q[0]).toFixed(1)},${sy(q[1]).toFixed(1)}`).join('');
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <line x1="0" x2="${W}" y1="${sy(0).toFixed(1)}" y2="${sy(0).toFixed(1)}" stroke="#2a3040" stroke-width="1" vector-effect="non-scaling-stroke"/>
      <path d="${d}" fill="none" stroke="${colorOf(p)}" stroke-width="2" ${dashed(p) ? 'stroke-dasharray="6 4"' : ''}
            stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
  }

  function renderCards() {
    const el = document.getElementById('cards');
    if (!data.portfolios.length) { el.innerHTML = '<div class="empty-state">هیچ سبدی تعریف نشده (config/portfolios.json).</div>'; return; }
    el.innerHTML = data.portfolios.map((p) => `
      <article class="card pcard ${filter === p.label ? 'selected' : ''}" data-label="${esc(p.label)}" title="${esc(p.description)}">
        <header>${keyHtml(p)}<strong>${esc(p.title)}</strong><span class="badge neutral">v${fa0.format(p.version)}</span></header>
        <div class="eq">${toman(p.equity)} <small>تومان</small></div>
        <div class="delta ${cls(p.return_pct)}">${pct(p.return_pct)}</div>
        <div class="metrics">
          <div><span>وین‌ریت</span><b>${p.win_rate == null ? '—' : pct(p.win_rate, 0).replace('+', '')}</b></div>
          <div><span>معاملهٔ بسته</span><b>${fa0.format(p.closed_count)}</b></div>
          <div><span>پوزیشن باز</span><b>${fa0.format(p.open_count)}</b></div>
          <div><span>امید هر معامله</span><b>${p.expectancy == null ? '—' : signed(toman(p.expectancy), p.expectancy)}</b></div>
          <div><span>Profit factor</span><b>${p.profit_factor == null ? '—' : fa2.format(p.profit_factor)}</b></div>
          <div><span>بیشترین افت</span><b>${pct(p.max_drawdown_pct).replace('+', '')}</b></div>
          <div><span>سود/زیان باز</span><b>${signed(toman(p.unrealized), p.unrealized)}</b></div>
          <div><span>کارمزد پرداختی</span><b>${toman(p.fees)}</b></div>
          <div><span>تایم‌فریم</span><b>${[...new Set(p.sources.map((s) => s.split('@')[1]))].map((r) => fa0.format(+r)).join('، ')} دقیقه</b></div>
        </div>
        ${spark(p)}
      </article>`).join('');
    el.querySelectorAll('.pcard').forEach((card) =>
      card.addEventListener('click', () => { filter = filter === card.dataset.label ? 'all' : card.dataset.label; renderAll(); }));
  }

  function renderEquity() {
    document.getElementById('legend').innerHTML = data.portfolios.map((p) => `<span>${keyHtml(p)}${esc(p.title)}</span>`).join('');
    for (const p of data.portfolios) {
      let series = equitySeries.get(p.label);
      if (!series) {
        series = equityChart.addLineSeries({
          color: colorOf(p), lineWidth: 2, lineStyle: dashed(p) ? 2 : 0, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerRadius: 4, crosshairMarkerBorderColor: SURFACE, crosshairMarkerBorderWidth: 2,
        });
        equitySeries.set(p.label, series);
        if (!zeroLine) zeroLine = series.createPriceLine({ price: 0, color: '#3a4256', lineWidth: 1, lineStyle: 0, axisLabelVisible: false });
      }
      series.applyOptions({ visible: filter === 'all' || filter === p.label });
      series.setData(p.curve.map(([time, value]) => ({ time, value })));
    }
  }

  function renderFilterChips() {
    const chips = [{ label: 'all', title: 'همهٔ سبدها' }, ...data.portfolios];
    const el = document.getElementById('filter-chips');
    el.innerHTML = chips.map((c) => `<button type="button" class="chip ${filter === c.label ? 'on' : ''}" data-label="${esc(c.label)}">${c.label === 'all' ? '' : keyHtml(c)}${esc(c.title)}</button>`).join('');
    el.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { filter = b.dataset.label; renderAll(); }));
  }

  const visible = (rows) => (filter === 'all' ? rows : rows.filter((r) => r.portfolio === filter));

  function renderTables() {
    const open = visible(data.open_positions);
    document.getElementById('open-count').textContent = fa0.format(open.length);
    document.getElementById('open-body').innerHTML = open.length ? open.map((t) => {
      const ratio = t.unrealized != null && t.size_quote ? t.unrealized / t.size_quote : null;
      return `<tr>
        <td>${keyHtml(t)}${esc(t.title)}</td>
        <td><button type="button" class="link" data-symbol="${esc(t.symbol)}" data-res="${esc(t.resolution)}">${symbolText(t.symbol)}</button></td>
        <td>${dirBadge(t.direction)}</td>
        <td class="num">${priceText(t.symbol, t.entry_price)}</td>
        <td class="num">${priceText(t.symbol, t.price)}</td>
        <td class="num">${priceText(t.symbol, t.stop_loss)}</td>
        <td class="num">${priceText(t.symbol, t.take_profit)}</td>
        <td class="num">${toman(t.size_quote)}</td>
        <td class="num"><span class="${cls(t.unrealized)}">${t.unrealized == null ? '—' : signed(toman(t.unrealized), t.unrealized)} (${pct(ratio)})</span></td>
        <td class="muted-cell">${durationText(data.now - t.entry_time)}</td>
        <td class="reason" title="${esc(t.entry_reason)}">${esc(t.strategy_name)}@${esc(t.resolution)} — ${esc(t.entry_reason)}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="11" class="muted-cell" style="text-align:center">پوزیشن بازی نیست</td></tr>';

    const closed = visible(data.closed_trades);
    document.getElementById('closed-count').textContent = fa0.format(closed.length);
    document.getElementById('closed-body').innerHTML = closed.length ? closed.map((t) => `<tr>
        <td>${keyHtml(t)}${esc(t.title)}</td>
        <td><button type="button" class="link" data-symbol="${esc(t.symbol)}" data-res="${esc(t.resolution)}">${symbolText(t.symbol)}</button></td>
        <td>${dirBadge(t.direction)}</td>
        <td class="num">${priceText(t.symbol, t.entry_price)} ← ${priceText(t.symbol, t.exit_price)}</td>
        <td class="num"><span class="${cls(t.pnl)}">${signed(toman(t.pnl), t.pnl)} (${pct(t.size_quote ? t.pnl / t.size_quote : null)})</span></td>
        <td class="muted-cell">${timeText(t.exit_time)}</td>
        <td class="reason" title="${esc(t.exit_reason)}">${esc(t.exit_reason)}</td>
        <td class="reason" title="${esc(t.entry_reason)}">${esc(t.entry_reason)}</td>
      </tr>`).join('') : '<tr><td colspan="8" class="muted-cell" style="text-align:center">هنوز معامله‌ای بسته نشده</td></tr>';

    document.querySelectorAll('button.link[data-symbol]').forEach((b) =>
      b.addEventListener('click', () => { userPicked = true; selectSymbol(b.dataset.symbol, b.dataset.res); liveEl.scrollIntoView({ behavior: 'smooth', block: 'center' }); }));
  }

  function renderSymbolChips() {
    const symbols = [...new Map(visible(data.open_positions).map((t) => [t.symbol, t.resolution])).entries()];
    if (!userPicked && (!liveSymbol || !symbols.some(([s]) => s === liveSymbol)) && symbols.length) {
      selectSymbol(symbols[0][0], symbols[0][1]);
    }
    const el = document.getElementById('symbol-chips');
    el.innerHTML = symbols.length
      ? symbols.map(([s, r]) => `<button type="button" class="chip ${s === liveSymbol ? 'on' : ''}" data-symbol="${esc(s)}" data-res="${esc(r)}">${symbolText(s)}</button>`).join('')
      : '<span class="muted">پوزیشن بازی نیست — از جدول معامله‌های بسته یک نماد انتخاب کن.</span>';
    el.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { userPicked = true; selectSymbol(b.dataset.symbol, b.dataset.res); }));
    document.getElementById('res-chips').innerHTML = ['5', '15', '60'].map((r) =>
      `<button type="button" class="chip ${r === liveRes ? 'on' : ''}" data-res="${r}">${fa0.format(+r)} دقیقه</button>`).join('');
    document.querySelectorAll('#res-chips button').forEach((b) => b.addEventListener('click', () => selectSymbol(liveSymbol, b.dataset.res)));
  }

  function renderAll() {
    if (!data) return;
    renderHero();
    renderCards();
    renderEquity();
    renderFilterChips();
    renderTables();
    renderSymbolChips();
    updateLastBarFromLivePrice();
  }

  // ---------------------------------------------------------------- نمودار زنده

  function selectSymbol(symbol, resolution) {
    if (!symbol) return;
    const changed = symbol !== liveSymbol || resolution !== liveRes;
    liveSymbol = symbol;
    liveRes = RES_SEC[resolution] ? resolution : '15';
    if (changed) loadLive(true);
    if (data) renderSymbolChips();
  }

  async function loadLive(fit = false) {
    if (!liveSymbol) return;
    const response = await fetch(`/api/candles?symbol=${encodeURIComponent(liveSymbol)}&resolution=${liveRes}`, { credentials: 'same-origin' });
    if (!response.ok) return;
    const c = await response.json();
    const k = c.quote === 'IRT' ? 0.1 : 1;
    const bars = c.candles.map(([time, o, h, l, cl]) => ({ time, open: o * k, high: h * k, low: l * k, close: cl * k }));
    const ref = bars.length ? bars[bars.length - 1].close : 1;
    const precision = ref >= 1000 ? 0 : ref >= 1 ? 2 : 6;
    candles.applyOptions({ priceFormat: { type: 'price', precision, minMove: Math.pow(10, -precision) } });
    candles.setData(bars);
    lastBar = bars.length ? { ...bars[bars.length - 1] } : null;

    priceLines.forEach((line) => candles.removePriceLine(line));
    priceLines = [];
    for (const t of c.open) {
      const name = t.portfolio.split('@')[0];
      priceLines.push(candles.createPriceLine({ price: t.entry_price * k, color: NEUTRAL, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: `ورود ${name}` }));
      if (t.stop_loss != null) priceLines.push(candles.createPriceLine({ price: t.stop_loss * k, color: CRITICAL, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `SL ${name}` }));
      if (t.take_profit != null) priceLines.push(candles.createPriceLine({ price: t.take_profit * k, color: GOOD, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `TP ${name}` }));
    }

    const step = RES_SEC[liveRes];
    const first = bars.length ? bars[0].time : Infinity;
    const snap = (ts) => Math.floor(ts / step) * step;
    const markers = [];
    for (const t of [...c.closed, ...c.open]) {
      if (t.entry_time >= first) {
        markers.push({ time: snap(t.entry_time), position: t.direction === 'buy' ? 'belowBar' : 'aboveBar',
                       color: t.direction === 'buy' ? GOOD : CRITICAL, shape: t.direction === 'buy' ? 'arrowUp' : 'arrowDown' });
      }
      if (t.exit_time && t.exit_time >= first) {
        markers.push({ time: snap(t.exit_time), position: 'inBar', color: t.pnl > 0 ? GOOD : CRITICAL, shape: 'circle' });
      }
    }
    candles.setMarkers(markers.sort((a, b) => a.time - b.time));
    document.getElementById('live-title').textContent =
      `· ${symbolText(liveSymbol)} · ${fa0.format(+liveRes)} دقیقه · ${c.quote === 'IRT' ? 'تومان' : 'تتر'}`;
    if (fit) liveChart.timeScale().fitContent();
    updateLastBarFromLivePrice();
  }

  // کندل پایگاه داده هر چرخه به‌روز می‌شود؛ قیمت لحظه‌ای (هر ۱۰ ثانیه) آخرین کندل را زنده نگه می‌دارد
  function updateLastBarFromLivePrice() {
    if (!data || !lastBar || !liveSymbol) return;
    const price = data.prices[liveSymbol];
    const latest = price && Number(price.latest);
    if (!latest) return;
    const value = displayPrice(liveSymbol, latest);
    lastBar = { ...lastBar, close: value, high: Math.max(lastBar.high, value), low: Math.min(lastBar.low, value) };
    candles.update(lastBar);
  }

  // ---------------------------------------------------------------- بارگذاری

  async function loadOverview() {
    try {
      const response = await fetch('/api/overview', { credentials: 'same-origin' });
      if (response.redirected || !response.ok) { if (response.redirected) location.reload(); return; }
      data = await response.json();
      renderAll();
    } catch (err) {
      console.warn('overview failed', err);
    }
  }

  loadOverview();
  setInterval(loadOverview, 10000);
  setInterval(() => loadLive(false), 20000);
})();

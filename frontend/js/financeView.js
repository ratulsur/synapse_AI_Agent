/**
 * Finance View — live candlestick chart + AI analysis trigger.
 *
 * Requires TradingView lightweight-charts loaded as a global (see index.html CDN script).
 * All chart state is local — no store changes needed until "Generate Report" is clicked.
 *
 * Export: renderFinanceView(container, { onGenerateReport, onBack }) → { cleanup }
 */

import { getFinanceQuote } from './api.js';
import { esc } from './utils.js';

const PERIODS = [
  { v: '1d',  l: '1D'  },
  { v: '5d',  l: '5D'  },
  { v: '1mo', l: '1M'  },
  { v: '3mo', l: '3M'  },
  { v: '6mo', l: '6M'  },
  { v: '1y',  l: '1Y'  },
  { v: '2y',  l: '2Y'  },
];

const INTERVAL_OPTS = {
  '1d':  [['1m','1 Min'],['5m','5 Min'],['15m','15 Min'],['1h','1 Hour']],
  '5d':  [['5m','5 Min'],['15m','15 Min'],['1h','1 Hour'],['1d','1 Day']],
  '1mo': [['1h','1 Hour'],['1d','1 Day']],
  '3mo': [['1d','1 Day'],['1wk','1 Week']],
  '6mo': [['1d','1 Day'],['1wk','1 Week']],
  '1y':  [['1d','1 Day'],['1wk','1 Week'],['1mo','1 Month']],
  '2y':  [['1d','1 Day'],['1wk','1 Week'],['1mo','1 Month']],
};

const DEFAULT_INTERVAL = {
  '1d': '5m', '5d': '1h', '1mo': '1d', '3mo': '1d',
  '6mo': '1d', '1y': '1d', '2y': '1wk',
};

const INTRADAY = new Set(['1m', '5m', '15m', '1h']);

export function renderFinanceView(container, { onGenerateReport, onBack } = {}) {
  let chart = null;
  let isActive = true;
  let currentTicker = '';
  let currentPeriod = '1mo';
  let currentInterval = '1d';

  container.innerHTML = `
    <div class="view view-finance">

      <div class="finance-topbar">
        <button class="btn btn-sm btn-secondary" id="fin-back">&#8592; Dashboard</button>
        <h2 class="finance-title">Markets</h2>
      </div>

      <div class="finance-search-bar">
        <input
          id="fin-ticker"
          class="fin-ticker-input"
          type="text"
          placeholder="Ticker (e.g. AAPL, MSFT, BTC-USD)"
          autocomplete="off"
          spellcheck="false"
          maxlength="12"
        />

        <div class="fin-period-row" id="fin-period-row">
          ${PERIODS.map(p => `
            <button
              class="btn btn-sm fin-period-btn${p.v === '1mo' ? ' active' : ''}"
              data-period="${p.v}"
              type="button"
            >${p.l}</button>
          `).join('')}
        </div>

        <select id="fin-interval" class="fin-interval-select">
          <option value="1d">1 Day</option>
        </select>

        <button class="btn btn-primary" id="fin-load" type="button">Load Chart</button>
      </div>

      <div id="fin-error" class="fin-error" role="alert" hidden></div>

      <div id="fin-loading" class="fin-loading" hidden>
        <div class="spinner" role="status" aria-label="Fetching market data"></div>
        <span>Fetching market data&hellip;</span>
      </div>

      <div id="fin-content" hidden>

        <div class="fin-summary-row">
          <div class="fin-stat-card">
            <span class="fin-stat-label">Last Close</span>
            <span class="fin-stat-value" id="fs-close">—</span>
          </div>
          <div class="fin-stat-card">
            <span class="fin-stat-label">Period Change</span>
            <span class="fin-stat-value" id="fs-pct">—</span>
          </div>
          <div class="fin-stat-card">
            <span class="fin-stat-label">Trend</span>
            <span class="fin-stat-value" id="fs-trend">—</span>
          </div>
          <div class="fin-stat-card">
            <span class="fin-stat-label">Period High</span>
            <span class="fin-stat-value" id="fs-high">—</span>
          </div>
          <div class="fin-stat-card">
            <span class="fin-stat-label">Period Low</span>
            <span class="fin-stat-value" id="fs-low">—</span>
          </div>
          <div class="fin-stat-card">
            <span class="fin-stat-label">SMA 20</span>
            <span class="fin-stat-value" id="fs-sma20">—</span>
          </div>
          <div class="fin-stat-card">
            <span class="fin-stat-label">SMA 50</span>
            <span class="fin-stat-value" id="fs-sma50">—</span>
          </div>
          <div class="fin-stat-card">
            <span class="fin-stat-label">Avg Volume</span>
            <span class="fin-stat-value" id="fs-vol">—</span>
          </div>
        </div>

        <div class="fin-chart-wrap">
          <div id="fin-chart" class="fin-chart"></div>
        </div>

        <div class="fin-analyze-bar">
          <button class="btn btn-primary btn-lg" id="fin-analyze" type="button">
            Generate AI Analysis Report
          </button>
          <span class="fin-analyze-hint">
            Runs the full LangGraph pipeline on live OHLCV data for this ticker.
          </span>
        </div>

      </div>

    </div>
  `;

  // --- DOM refs ---
  const tickerInput  = container.querySelector('#fin-ticker');
  const periodBtns   = container.querySelectorAll('.fin-period-btn');
  const intervalSel  = container.querySelector('#fin-interval');
  const loadBtn      = container.querySelector('#fin-load');
  const errorEl      = container.querySelector('#fin-error');
  const loadingEl    = container.querySelector('#fin-loading');
  const contentEl    = container.querySelector('#fin-content');
  const analyzeBtn   = container.querySelector('#fin-analyze');
  const backBtn      = container.querySelector('#fin-back');

  // --- Interval dropdown management ---
  function syncIntervalOpts(period) {
    const opts = INTERVAL_OPTS[period] || [['1d', '1 Day']];
    const def  = DEFAULT_INTERVAL[period] || '1d';
    intervalSel.innerHTML = opts
      .map(([v, l]) => `<option value="${v}"${v === def ? ' selected' : ''}>${l}</option>`)
      .join('');
    currentInterval = def;
  }
  syncIntervalOpts(currentPeriod);

  periodBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      periodBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentPeriod = btn.dataset.period;
      syncIntervalOpts(currentPeriod);
    });
  });

  intervalSel.addEventListener('change', () => { currentInterval = intervalSel.value; });
  backBtn.addEventListener('click', () => { if (onBack) onBack(); });
  tickerInput.addEventListener('keydown', e => { if (e.key === 'Enter') loadChart(); });
  loadBtn.addEventListener('click', loadChart);

  analyzeBtn.addEventListener('click', () => {
    if (!currentTicker) return;
    const q = `Perform a comprehensive technical and fundamental analysis of ${currentTicker} stock. ` +
      `Use the Finance domain to fetch OHLCV data for the ${currentPeriod} period. ` +
      `Include price action, trend direction, support/resistance levels, SMA crossovers, ` +
      `volume patterns, candlestick signals, and a short-term outlook.`;
    if (onGenerateReport) onGenerateReport(q);
  });

  // --- Helpers ---
  function fmt(n, dec = 2) {
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }

  function fmtVol(n) {
    if (n == null) return '—';
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(Math.round(n));
  }

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.hidden  = false;
    contentEl.hidden  = true;
    loadingEl.hidden  = true;
  }

  // --- Chart rendering ---
  function renderChart(data) {
    loadingEl.hidden = true;
    errorEl.hidden   = true;
    contentEl.hidden = false;

    const s = data.summary;

    // Summary cards
    container.querySelector('#fs-close').textContent = '$' + fmt(s.last_close);

    const pctEl = container.querySelector('#fs-pct');
    const sign  = s.pct_change >= 0 ? '+' : '';
    pctEl.textContent  = `${sign}${fmt(s.pct_change)}%`;
    pctEl.className    = `fin-stat-value ${s.pct_change >= 0 ? 'fin-positive' : 'fin-negative'}`;

    const trendEl = container.querySelector('#fs-trend');
    trendEl.textContent = s.trend;
    trendEl.className   = `fin-stat-value fin-trend-${s.trend}`;

    container.querySelector('#fs-high').textContent  = '$' + fmt(s.period_high);
    container.querySelector('#fs-low').textContent   = '$' + fmt(s.period_low);
    container.querySelector('#fs-sma20').textContent = s.sma20 != null ? '$' + fmt(s.sma20) : 'N/A';
    container.querySelector('#fs-sma50').textContent = s.sma50 != null ? '$' + fmt(s.sma50) : 'N/A';
    container.querySelector('#fs-vol').textContent   = fmtVol(s.avg_volume);

    // Destroy previous chart
    if (chart) { chart.remove(); chart = null; }

    const chartEl = container.querySelector('#fin-chart');

    if (!window.LightweightCharts) {
      chartEl.innerHTML = '<p class="fin-no-chart">Chart library unavailable — try refreshing.</p>';
      return;
    }

    chart = LightweightCharts.createChart(chartEl, {
      width:  chartEl.clientWidth || 860,
      height: 420,
      layout: {
        background: { color: '#0f172a' },
        textColor:  '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair:       { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale:       { borderColor: '#334155', timeVisible: true, secondsVisible: false },
    });

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor:      '#22c55e',
      downColor:    '#ef4444',
      borderVisible: false,
      wickUpColor:  '#22c55e',
      wickDownColor:'#ef4444',
    });

    const intraday = INTRADAY.has(currentInterval);
    const toTime   = t => intraday ? parseInt(t, 10) : t;

    candleSeries.setData(data.bars.map(b => ({
      time:  toTime(b.time),
      open:  b.open, high: b.high, low: b.low, close: b.close,
    })));

    // SMA 20 overlay
    if (s.sma20 != null && data.bars.length >= 20) {
      const smaSeries = chart.addLineSeries({ color: '#f59e0b', lineWidth: 1, title: 'SMA20', priceLineVisible: false });
      const smaData = data.bars.slice(19).map((b, i) => {
        const slice = data.bars.slice(i, i + 20);
        const avg   = slice.reduce((sum, x) => sum + x.close, 0) / slice.length;
        return { time: toTime(b.time), value: avg };
      });
      smaSeries.setData(smaData);
    }

    // SMA 50 overlay
    if (s.sma50 != null && data.bars.length >= 50) {
      const sma50Series = chart.addLineSeries({ color: '#a78bfa', lineWidth: 1, title: 'SMA50', priceLineVisible: false });
      const sma50Data = data.bars.slice(49).map((b, i) => {
        const slice = data.bars.slice(i, i + 50);
        const avg   = slice.reduce((sum, x) => sum + x.close, 0) / slice.length;
        return { time: toTime(b.time), value: avg };
      });
      sma50Series.setData(sma50Data);
    }

    // Volume histogram
    const volSeries = chart.addHistogramSeries({
      priceFormat:   { type: 'volume' },
      priceScaleId:  '',
      scaleMargins:  { top: 0.82, bottom: 0 },
    });
    volSeries.setData(data.bars.map(b => ({
      time:  toTime(b.time),
      value: b.volume,
      color: b.close >= b.open ? '#22c55e44' : '#ef444444',
    })));

    chart.timeScale().fitContent();

    // Responsive resize
    const ro = new ResizeObserver(() => {
      if (chart && chartEl.clientWidth > 0) chart.applyOptions({ width: chartEl.clientWidth });
    });
    ro.observe(chartEl);
  }

  // --- Load ---
  async function loadChart() {
    const raw = tickerInput.value.trim().toUpperCase();
    if (!raw) { showError('Please enter a ticker symbol (e.g. AAPL).'); return; }
    if (!/^[A-Z0-9.\-^=]{1,12}$/.test(raw)) { showError('Invalid ticker format.'); return; }

    currentTicker   = raw;
    errorEl.hidden  = true;
    contentEl.hidden= true;
    loadingEl.hidden= false;

    try {
      const data = await getFinanceQuote(raw, { period: currentPeriod, interval: currentInterval });
      if (!isActive) return;
      renderChart(data);
    } catch (err) {
      if (!isActive) return;
      const msg = err?.body?.detail || err?.message || 'Failed to load market data.';
      showError(`Error: ${msg}`);
    }
  }

  return {
    cleanup() {
      isActive = false;
      if (chart) { chart.remove(); chart = null; }
    },
  };
}

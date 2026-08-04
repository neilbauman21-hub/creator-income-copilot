'use strict';

/* ============================================================
   Creator Income Copilot — dashboard frontend
   Talks to POST /api/analyze (multipart file) and
   POST /api/sample/analyze. Renders the full AnalyzeResponse.
   ============================================================ */

/* ---------- tiny helpers ---------- */

const $ = (sel) => document.querySelector(sel);

const FONT = "'Inter', system-ui, sans-serif";

// Escape user/CSV-derived strings before injecting into HTML.
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

const num = (n) => Number(n) || 0;

const fmtMoney = (n) => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD',
  minimumFractionDigits: 2, maximumFractionDigits: 2,
}).format(num(n));

const fmtNum = (n) => new Intl.NumberFormat('en-US').format(num(n));

const fmtPct = (n) => `${num(n).toFixed(1)}%`;

// Compact USD for chart axis ticks (e.g. "$1.2K").
const fmtMoneyCompact = (n) => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', notation: 'compact',
  maximumFractionDigits: 1,
}).format(num(n));

const SIGNAL_LABEL = {
  high_refund_rate: 'High refund rate',
  low_repeat_rate: 'Low repeat rate',
  slowing_sales: 'Slowing sales',
  other: 'Signal',
};

// Direction badge: up = green, down = red, flat = gray.
function dirBadge(direction, pct) {
  const d = String(direction || 'flat').toLowerCase();
  const arrow = d === 'up' ? '&#9650;' : d === 'down' ? '&#9660;' : '&#8212;';
  const cls = d === 'up' ? 'badge-up' : d === 'down' ? 'badge-down' : 'badge-flat';
  const magnitude = Math.abs(num(pct));
  const txt = magnitude > 0
    ? (d === 'up' ? '+' : d === 'down' ? '&#8722;' : '') + magnitude.toFixed(1) + '%'
    : '0%';
  return `<span class="badge ${cls}">${arrow} ${txt}</span>`;
}

/* ---------- panel states (error / empty) ---------- */

// Replace a panel's contents with an inline error + Retry button.
// retryFn re-runs the original renderer; failures re-render the error state.
function panelError(container, retryFn) {
  container.innerHTML =
    '<div class="panel-error" role="alert">' +
    '<p class="panel-error-msg">Failed to load this section.</p>' +
    '<button type="button" class="btn btn-small btn-secondary panel-retry">Retry</button>' +
    '</div>';
  const btn = container.querySelector('.panel-retry');
  btn.addEventListener('click', () => {
    try { retryFn(); } catch (_) { panelError(container, retryFn); }
  });
}

// Friendly empty-state message for list panels.
const emptyItem = (msg) => `<li class="empty">${esc(msg)}</li>`;

/* ---------- loading overlay (staged status) ---------- */

const STAGES = ['Parsing CSV...', 'Crunching numbers...', 'Generating AI insights...'];
let stageTimer = null;

function setStage(i) {
  document.querySelectorAll('#stageList li').forEach((li, idx) => {
    li.classList.toggle('done', idx < i);
    li.classList.toggle('active', idx === i);
  });
  $('#stageTitle').textContent = STAGES[i];
}

function showOverlay() {
  $('#overlay').hidden = false;
  document.body.classList.add('loading');
  setStage(0);
  let i = 0;
  clearInterval(stageTimer);
  stageTimer = setInterval(() => {
    i = Math.min(i + 1, STAGES.length - 1);
    setStage(i);
    if (i === STAGES.length - 1) clearInterval(stageTimer);
  }, 2200);
}

function hideOverlay() {
  clearInterval(stageTimer);
  $('#overlay').hidden = true;
  document.body.classList.remove('loading');
}

/* ---------- toast ---------- */

let toastTimer = null;

function showToast(msg, kind = 'error') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = `toast ${kind}`;
  t.hidden = false;
  // force reflow so the transition replays
  void t.offsetWidth;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    t.classList.remove('show');
    setTimeout(() => { t.hidden = true; }, 350);
  }, 6000);
}

/* ---------- data fetching ---------- */

async function analyze(url, options) {
  showOverlay();
  try {
    const res = await fetch(url, options);
    if (!res.ok) {
      let detail = `Request failed (HTTP ${res.status})`;
      try {
        const j = await res.json();
        if (j && j.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
      } catch (_) { /* non-JSON error body */ }
      throw new Error(detail);
    }
    const data = await res.json();
    render(data);
    hideOverlay();
  } catch (err) {
    hideOverlay();
    showToast(err && err.message ? err.message : 'Something went wrong. Please try again.');
    // per-panel error states — every section shows "Failed to load" + Retry
    const retry = () => analyze(url, options);
    panelError($('#kpiGrid'), retry);
    panelError($('.chart-wrap'), retry);
    panelError($('#topProducts'), retry);
    panelError($('#trendsList'), retry);
    panelError($('#churnList'), retry);
    panelError($('#insightsList'), retry);
    $('#btnDownloadCsv').disabled = true;
    $('#results').hidden = false;
  }
}

function handleFile(file) {
  if (!/\.(csv|txt)$/i.test(file.name || '')) {
    showToast('Please upload a .csv or .txt file.');
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    showToast('That file is larger than the 5 MB limit.');
    return;
  }
  const fd = new FormData();
  fd.append('file', file);
  analyze('/api/analyze', { method: 'POST', body: fd });
}

function loadSample() {
  analyze('/api/sample/analyze', { method: 'POST' });
}

/* ---------- renderers ---------- */

let lastData = null; // latest successful report (for CSV download + retries)

function render(data) {
  lastData = data;
  const a = data.analytics || {};
  const ins = data.insights || {};

  // period line under the results header
  const range = [a.period_start, a.period_end].filter(Boolean);
  $('#periodRange').textContent = range.length === 2 ? `${range[0]}  →  ${range[1]}` : '';

  // Each panel renders independently: a failure in one shows an inline
  // "Failed to load" + Retry state instead of killing the whole dashboard.
  try { renderKpis(a); } catch (_) { panelError($('#kpiGrid'), () => renderKpis(a)); }
  try { renderChart(a); } catch (_) { panelError($('.chart-wrap'), () => renderChart(a)); }
  try { renderTopProducts(a.top_products || []); } catch (_) { panelError($('#topProducts'), () => renderTopProducts(a.top_products || [])); }
  try { renderTrends(a.trends || []); } catch (_) { panelError($('#trendsList'), () => renderTrends(a.trends || [])); }
  try { renderChurn(a.churn_signals || []); } catch (_) { panelError($('#churnList'), () => renderChurn(a.churn_signals || [])); }
  try { renderInsights(ins); } catch (_) { panelError($('#insightsList'), () => renderInsights(ins)); }
  try { renderWarnings(data.warnings || []); } catch (_) { /* warnings card hides itself when empty */ }

  $('#btnDownloadCsv').disabled = false;
  $('#results').hidden = false;
  $('#results').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderKpis(a) {
  const hasSales = num(a.total_orders) > 0 || (a.revenue_by_day || []).length > 0;
  if (!hasSales) {
    $('#kpiGrid').innerHTML = '<p class="empty kpi-empty">No sales found in this dataset — upload a CSV with orders to see your numbers here.</p>';
    return;
  }
  const cards = [
    { label: 'Total revenue', value: fmtMoney(a.total_revenue), sub: 'Net of refunds', accent: 'accent-violet' },
    { label: 'Orders', value: fmtNum(a.total_orders), sub: `${fmtNum(a.unique_customers)} unique customers`, accent: 'accent-blue' },
    { label: 'Avg order value', value: fmtMoney(a.avg_order_value), sub: 'Per paid order', accent: 'accent-teal' },
    { label: 'Repeat purchase rate', value: fmtPct(a.repeat_purchase_rate), sub: 'Customers with 2+ orders', accent: 'accent-amber' },
  ];
  $('#kpiGrid').innerHTML = cards.map((c) => `
    <div class="card kpi ${c.accent}">
      <p class="kpi-label">${esc(c.label)}</p>
      <p class="kpi-value">${esc(c.value)}</p>
      <p class="kpi-sub">${esc(c.sub)}</p>
    </div>`).join('');
}

let chart = null;

function renderChart(a) {
  const wrap = $('.chart-wrap');
  const days = a.revenue_by_day || [];

  if (typeof Chart === 'undefined') {
    wrap.innerHTML = '<p class="empty">Chart.js failed to load (CDN unreachable).</p>';
    return;
  }
  if (!days.length) {
    if (chart) { chart.destroy(); chart = null; }
    wrap.innerHTML = '<p class="empty">No daily revenue data yet — your revenue-over-time chart will appear here.</p>';
    return;
  }
  // restore the canvas if it was replaced by an empty-state message
  if (!wrap.querySelector('canvas')) {
    wrap.innerHTML = '<canvas id="revenueChart"></canvas>';
  }

  const ctx = $('#revenueChart').getContext('2d');
  if (chart) chart.destroy();

  const labels = days.map((d) => d.date);
  const revenue = days.map((d) => num(d.revenue));
  const orders = days.map((d) => num(d.orders));

  const grad = ctx.createLinearGradient(0, 0, 0, 300);
  grad.addColorStop(0, 'rgba(79, 70, 229, 0.12)');
  grad.addColorStop(1, 'rgba(79, 70, 229, 0)');

  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Revenue',
          data: revenue,
          borderColor: '#4f46e5',
          backgroundColor: grad,
          fill: true,
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointBackgroundColor: '#4f46e5',
          pointBorderColor: '#4f46e5',
        },
        {
          label: 'Orders',
          data: orders,
          type: 'bar',
          yAxisID: 'yOrders',
          backgroundColor: 'rgba(156, 163, 175, 0.35)',
          hoverBackgroundColor: 'rgba(156, 163, 175, 0.55)',
          borderRadius: 3,
          barPercentage: 0.55,
          categoryPercentage: 0.7,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: { color: '#6b7280', usePointStyle: true, pointStyle: 'circle', boxWidth: 7, font: { family: FONT, size: 12 } },
        },
        tooltip: {
          backgroundColor: '#111827',
          borderColor: 'rgba(17, 24, 39, 0.1)',
          borderWidth: 1,
          padding: 10,
          titleColor: '#f9fafb',
          bodyColor: '#e5e7eb',
          cornerRadius: 8,
          callbacks: {
            label: (c) => (c.dataset.label === 'Revenue'
              ? ` ${c.dataset.label}: ${fmtMoney(c.parsed.y)}`
              : ` ${c.dataset.label}: ${c.parsed.y}`),
          },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(17, 24, 39, 0.05)' },
          ticks: { color: '#9ca3af', maxTicksLimit: 10, font: { family: FONT, size: 11 } },
        },
        y: {
          position: 'left',
          grid: { color: 'rgba(17, 24, 39, 0.06)' },
          ticks: { color: '#9ca3af', callback: (v) => fmtMoneyCompact(v), font: { family: FONT, size: 11 } },
        },
        yOrders: {
          position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { color: '#9ca3af', precision: 0, font: { family: FONT, size: 11 } },
        },
      },
    },
  });
}

function renderTopProducts(products) {
  const el = $('#topProducts');
  if (!products.length) {
    el.innerHTML = emptyItem('No products in this dataset yet — top sellers will show up here.');
    return;
  }
  el.innerHTML = products.map((p, i) => {
    const share = Math.max(0, Math.min(100, num(p.share_pct)));
    const refunds = num(p.refunds);
    const refundNote = refunds > 0
      ? `<span class="refund-note">${fmtNum(refunds)} refund${refunds === 1 ? '' : 's'}</span>`
      : '';
    return `
      <li class="product-item">
        <div class="product-top">
          <span class="rank">${i + 1}</span>
          <span class="product-name" title="${esc(p.name)}">${esc(p.name)}</span>
          <span class="product-stats">${fmtMoney(p.revenue)} <span class="muted">&middot; ${fmtNum(p.units)} units</span></span>
          ${dirBadge(p.momentum, p.momentum_pct)}
        </div>
        <div class="share-track"><div class="share-fill" style="width:${share}%"></div></div>
        <div class="product-bottom">
          <span class="share-label">${share.toFixed(0)}% of revenue</span>
          <span class="product-meta">avg ${fmtMoney(p.avg_price)}${refundNote ? ` &middot; ${refundNote}` : ''}</span>
        </div>
      </li>`;
  }).join('');
}

function renderTrends(trends) {
  const el = $('#trendsList');
  if (!trends.length) {
    el.innerHTML = emptyItem('Not enough history to spot trends yet — keep selling and check back.');
    return;
  }
  el.innerHTML = trends.map((t) => `
    <li class="signal-item">
      ${dirBadge(t.direction, t.magnitude_pct)}
      <div class="signal-text">
        <p class="signal-title">${esc(t.label)}</p>
        ${t.description ? `<p class="signal-desc">${esc(t.description)}</p>` : ''}
      </div>
    </li>`).join('');
}

function renderChurn(signals) {
  const el = $('#churnList');
  if (!signals.length) {
    el.innerHTML = emptyItem('No churn signals detected \u2014 healthy store.');
    return;
  }
  el.innerHTML = signals.map((s) => {
    const sev = String(s.severity || 'low').toLowerCase();
    const chipCls = sev === 'high' ? 'chip-high' : sev === 'medium' ? 'chip-medium' : 'chip-low';
    return `
      <li class="signal-item churn-item">
        <div class="churn-head">
          <span class="product-name">${esc(s.product)}</span>
          <span class="chip ${chipCls}">${esc(sev)}</span>
        </div>
        <p class="signal-title">${esc(SIGNAL_LABEL[s.signal_type] || 'Signal')}</p>
        ${s.description ? `<p class="signal-desc">${esc(s.description)}</p>` : ''}
      </li>`;
  }).join('');
}

function renderInsights(ins) {
  // insights list
  const list = ins.insights || [];
  $('#insightsList').innerHTML = list.length
    ? list.map((t) => `<li>${esc(t)}</li>`).join('')
    : emptyItem('No insights generated for this dataset yet.');

  // heuristic-mode chip
  $('#fallbackChip').hidden = !ins.used_fallback;

  // promo email
  const pe = ins.promo_email || {};
  $('#promoSubject').textContent = pe.subject || '(no subject)';
  $('#promoBody').textContent = pe.body || '(no body)';
  $('#btnCopy').disabled = !pe.body;

  // next product
  const np = ins.next_product || {};
  const npEl = $('#nextProduct');
  if (np.name) {
    npEl.innerHTML = `
      <p class="np-name">${esc(np.name)}</p>
      <div class="np-block">
        <span class="np-label">Why</span>
        <p>${esc(np.rationale)}</p>
      </div>
      ${np.evidence ? `
      <div class="np-block">
        <span class="np-label">Evidence</span>
        <p class="np-evidence">${esc(np.evidence)}</p>
      </div>` : ''}`;
  } else {
    npEl.innerHTML = '<p class="empty">Not enough data for a next-product recommendation yet.</p>';
  }
}

function renderWarnings(warnings) {
  const card = $('#warningsCard');
  if (!warnings || !warnings.length) { card.hidden = true; return; }
  $('#warningsList').innerHTML = warnings.map((w) => `<li>${esc(w)}</li>`).join('');
  card.hidden = false;
}

/* ---------- CSV report download ---------- */

// Quote CSV fields that contain commas, quotes or newlines.
// CSV formula-injection guard: fields starting with =, +, -, @ (optionally
// after leading whitespace / tab / CR) can be executed as formulas / DDE
// links when the file is opened in Excel/Sheets (product names come from the
// uploaded CSV, i.e. untrusted). Leading whitespace is covered because some
// spreadsheet apps trim it before re-parsing the cell.
// Prefixing a single quote renders them as plain text. Applied BEFORE
// quoting so the apostrophe lands inside the quoted field.
const csvEscape = (v) => {
  const s = String(v == null ? '' : v);
  const safe = /^\s*[=+\-@]/.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};

// Build a CSV from the analytics JSON: header summary, revenue by day,
// and top products. All money as plain USD numbers.
function buildReportCsv(a) {
  const lines = [];
  const period = [a.period_start, a.period_end].filter(Boolean).join(' to ');
  lines.push('Creator Income Copilot - report');
  lines.push(`Period,${csvEscape(period)}`);
  lines.push(`Total revenue (USD),${num(a.total_revenue).toFixed(2)}`);
  lines.push(`Total orders,${num(a.total_orders)}`);
  lines.push(`Unique customers,${num(a.unique_customers)}`);
  lines.push(`Avg order value (USD),${num(a.avg_order_value).toFixed(2)}`);
  lines.push(`Repeat purchase rate,${num(a.repeat_purchase_rate).toFixed(2)}%`);
  lines.push('');
  lines.push('Revenue by day');
  lines.push('Date,Revenue (USD),Orders');
  (a.revenue_by_day || []).forEach((d) => {
    lines.push([csvEscape(d.date), num(d.revenue).toFixed(2), num(d.orders)].join(','));
  });
  lines.push('');
  lines.push('Top products');
  lines.push('Rank,Product,Revenue (USD),Units,Share %');
  (a.top_products || []).forEach((p, i) => {
    lines.push([i + 1, csvEscape(p.name), num(p.revenue).toFixed(2), num(p.units), num(p.share_pct).toFixed(1)].join(','));
  });
  return lines.join('\n');
}

function downloadReport() {
  if (!lastData) return;
  const csv = buildReportCsv(lastData.analytics || {});
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `creator-income-report-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ---------- copy promo email ---------- */

$('#btnCopy').addEventListener('click', async () => {
  const subject = $('#promoSubject').textContent;
  const body = $('#promoBody').textContent;
  const text = `Subject: ${subject}\n\n${body}`;
  const btn = $('#btnCopy');

  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    // clipboard API unavailable (e.g. insecure context) — fall back
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }

  btn.textContent = 'Copied!';
  btn.classList.add('btn-success');
  setTimeout(() => {
    btn.textContent = 'Copy email';
    btn.classList.remove('btn-success');
  }, 2000);
});

/* ---------- wiring ---------- */

const fileInput = $('#fileInput');

// shortcut hints
$('#btnUploadTop').title = 'Keyboard shortcut: U';
$('#btnSample').title = 'Keyboard shortcut: S';
$('#btnSampleTop').title = 'Keyboard shortcut: S';

$('#btnUploadTop').addEventListener('click', () => fileInput.click());

$('#btnDownloadCsv').addEventListener('click', downloadReport);

// footer year
const yearEl = $('#year');
if (yearEl) yearEl.textContent = new Date().getFullYear();

// keyboard shortcuts: U = upload, S = sample data
document.addEventListener('keydown', (e) => {
  // ignore auto-repeat (held keys) and shortcuts while an analysis is in flight
  if (e.repeat || document.body.classList.contains('loading')) return;
  const t = e.target;
  const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT'
    || t.isContentEditable || (t.getAttribute && t.getAttribute('contenteditable') === 'true'));
  if (typing || e.altKey || e.ctrlKey || e.metaKey) return;
  const k = String(e.key || '').toLowerCase();
  if (k === 'u') { e.preventDefault(); fileInput.click(); }
  else if (k === 's') { e.preventDefault(); loadSample(); }
});

$('#btnNewUpload').addEventListener('click', () => {
  $('#results').hidden = true;
  $('#uploadSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

fileInput.addEventListener('change', (e) => {
  const f = e.target.files && e.target.files[0];
  if (f) handleFile(f);
  e.target.value = ''; // allow re-selecting the same file
});

$('#btnSample').addEventListener('click', loadSample);
$('#btnSampleTop').addEventListener('click', loadSample);

// drag & drop
const dz = $('#dropZone');
['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault();
  dz.classList.add('dragover');
}));
['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault();
  dz.classList.remove('dragover');
}));
dz.addEventListener('drop', (e) => {
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) handleFile(f);
});
dz.addEventListener('click', () => fileInput.click());
dz.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    fileInput.click();
  }
});

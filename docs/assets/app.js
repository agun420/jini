const DATA_PATHS = {
  signals: [
    "data/prediction_engine/signal_dashboard_market_guard_enriched.json",
    "data/prediction_engine/signal_dashboard_quality_enriched.json",
    "data/prediction_engine/signal_dashboard_news_enriched.json",
    "data/prediction_engine/signal_dashboard_finra_enriched.json",
    "data/prediction_engine/signal_dashboard_enriched.json",
    "data/prediction_engine/signal_dashboard.json"
  ],
  freeScanner: "data/prediction_engine/free_scanner.json",
  health: [
    "data/prediction_engine/alpaca_market_scanner_health.json",
    "data/prediction_engine/alpaca_news_health.json",
    "data/prediction_engine/slippage_fill_tracker_health.json",
    "data/prediction_engine/real_money_readiness_guard_health.json",
    "data/prediction_engine/halt_luld_circuit_guard_health.json",
    "data/prediction_engine/advanced_signal_quality_health.json",
    "data/prediction_engine/paper_execution_gate_health.json",
    "data/prediction_engine/adaptive_guard_health.json",
    "data/prediction_engine/outcome_labeler_health.json",
    "data/prediction_engine/signal_journal_health.json",
    "data/prediction_engine/finra_short_pressure_health.json",
    "data/prediction_engine/sec_catalyst_health.json",
    "data/prediction_engine/scanner_health.json"
  ],
  adaptiveGuard: "data/prediction_engine/adaptive_guard.json",
  paperPlan: "data/prediction_engine/paper_order_plan.json",
  outcomes: "data/prediction_engine/outcomes.json",
  learning: "data/prediction_engine/learning.json",
  realMoneyReadiness: "data/prediction_engine/real_money_readiness_guard.json",
  slippage: "data/prediction_engine/slippage_fill_tracker.json",
  quality: "data/prediction_engine/advanced_signal_quality.json"
};

const state = {
  signalsPayload: {},
  signals: [],
  health: [],
  adaptiveGuard: {},
  paperPlan: {},
  outcomes: {},
  learning: {},
  realMoneyReadiness: {},
  slippage: {},
  quality: {}
};

function byId(id) {
  return document.getElementById(id);
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "N/A";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return num.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function money(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return `$${num.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function pct(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return `${num.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
}

function chipClass(status) {
  if (status === "TRADE_ELIGIBLE" || status === "TRADE ELIGIBLE") return "green";
  if (status === "WAIT_FOR_PULLBACK" || status === "WAIT FOR PULLBACK") return "orange";
  if (status === "ALERT_ONLY" || status === "ALERT ONLY") return "blue";
  if (status === "WATCH_ONLY" || status === "WATCH ONLY") return "yellow";
  if (status === "NO_TRADE" || status === "NO TRADE") return "red";
  return "";
}

async function fetchJson(path) {
  const res = await fetch(`${path}?v=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json();
}

async function fetchFirst(paths) {
  const errors = [];
  for (const path of paths) {
    try {
      const data = await fetchJson(path);
      return { data, path };
    } catch (err) {
      errors.push(`${path}: ${err.message}`);
    }
  }
  return { data: {}, path: "none", errors };
}

async function fetchOptional(path) {
  try {
    return await fetchJson(path);
  } catch {
    return {};
  }
}

async function fetchHealth() {
  const results = [];
  for (const path of DATA_PATHS.health) {
    try {
      const data = await fetchJson(path);
      results.push({ path, data, ok: true });
    } catch (err) {
      results.push({ path, ok: false, error: err.message });
    }
  }
  return results;
}

function normalizeSignals(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload.rows)) return payload.rows;
  if (Array.isArray(payload.signals)) return payload.signals;
  return [];
}

function renderMetrics() {
  const counts = state.signalsPayload.counts || {};
  const guard = state.adaptiveGuard.guard || {};
  const orderPlan = state.paperPlan.order_plan || {};
  const selected = state.paperPlan.selected_candidate || {};

  byId("metric-total-signals").textContent = fmt(counts.total ?? state.signals.length, 0);
  byId("metric-trade-eligible").textContent = fmt(counts.trade_eligible ?? counts.buy_watch ?? 0, 0);
  byId("metric-signal-source").textContent = state.signalsPayload.__sourcePath || "signal source";

  byId("metric-risk-mode").textContent = guard.risk_mode || "N/A";
  const reasons = Array.isArray(guard.reasons) ? guard.reasons : [];
  byId("metric-guard-reason").textContent = reasons[0] || "guard not loaded";

  byId("metric-order-plan").textContent = orderPlan.created ? "Created" : "Not Created";
  byId("metric-order-selected").textContent = selected.ticker ? `Selected ${selected.ticker}` : "no selected ticker";

  const ok = state.health.some(item => item.ok);
  byId("global-status").textContent = ok ? "Data loaded" : "No data";
  byId("global-status").className = `status-pill ${ok ? "chip green" : "chip red"}`;
}

function renderTopSetup() {
  const top = state.signals.find(row => row.status === "TRADE_ELIGIBLE") ||
              state.signalsPayload.best_trade_eligible;

  const topStatus = byId("top-status");
  const box = byId("top-setup");

  if (!top) {
    topStatus.textContent = "No Trade Eligible";
    topStatus.className = "chip red";
    box.innerHTML = `
      <p class="muted">No Trade Eligible signal is available right now.</p>
      <p class="muted">This is normal when data is stale, VWAP/RVOL is missing, or the adaptive gate is defensive.</p>
    `;
    return;
  }

  topStatus.textContent = top.status || top.signal || "TRADE_ELIGIBLE";
  topStatus.className = `chip ${chipClass(top.status || top.signal)}`;

  box.innerHTML = `
    <h3>${top.ticker || "N/A"}</h3>
    <p class="muted">${top.trade_gate_summary || top.reason || "No reason provided."}</p>
    <div class="top-setup-grid">
      <div class="mini"><small>Score</small><strong>${fmt(top.score)}</strong></div>
      <div class="mini"><small>Price</small><strong>${money(top.price)}</strong></div>
      <div class="mini"><small>RVOL</small><strong>${fmt(top.relative_volume)}</strong></div>
      <div class="mini"><small>Entry</small><strong>${money(top.entry)}</strong></div>
      <div class="mini"><small>Target</small><strong>${money(top.target)}</strong></div>
      <div class="mini"><small>Stop</small><strong>${money(top.stop)}</strong></div>
    </div>
  `;
}

function renderAdaptiveGuard() {
  const payload = state.adaptiveGuard || {};
  const guard = payload.guard || {};
  const panel = byId("adaptive-guard-panel");
  const allow = guard.allow_new_entries;

  byId("guard-allow").textContent = allow === false ? "Blocked" : "Allowed";
  byId("guard-allow").className = `chip ${allow === false ? "red" : "green"}`;

  const reasons = Array.isArray(guard.reasons) ? guard.reasons : [];
  panel.innerHTML = `
    <div class="kv"><span>Risk mode</span><span>${guard.risk_mode || "N/A"}</span></div>
    <div class="kv"><span>Allow new entries</span><span>${allow === false ? "No" : "Yes"}</span></div>
    <div class="kv"><span>Min score</span><span>${fmt(guard.min_score_required)}</span></div>
    <div class="kv"><span>Max notional</span><span>${money(guard.max_notional_per_trade)}</span></div>
    <div class="kv"><span>Reasons</span><span>${reasons.join(", ") || "N/A"}</span></div>
  `;
}

function renderPaperPlan() {
  const payload = state.paperPlan || {};
  const plan = payload.order_plan || {};
  const order = plan.order || {};
  const submission = payload.submission || {};
  const account = payload.account_snapshot || {};
  const panel = byId("paper-plan-panel");

  panel.innerHTML = `
    <div class="kv"><span>Plan created</span><span>${plan.created ? "Yes" : "No"}</span></div>
    <div class="kv"><span>Reason</span><span>${plan.reason || "N/A"}</span></div>
    <div class="kv"><span>Symbol</span><span>${order.symbol || "N/A"}</span></div>
    <div class="kv"><span>Qty</span><span>${order.qty || "N/A"}</span></div>
    <div class="kv"><span>Estimated notional</span><span>${money(order.estimated_notional)}</span></div>
    <div class="kv"><span>Submitted</span><span>${submission.submitted ? "Yes" : "No"}</span></div>
    <div class="kv"><span>Submission reason</span><span>${submission.reason || "N/A"}</span></div>
    <div class="kv"><span>Buying power</span><span>${money(account.buying_power)}</span></div>
  `;
}

function renderOutcomes() {
  const payload = state.outcomes || {};
  const summary = payload.summary || {};
  const labels = summary.outcomes_by_label || {};
  const panel = byId("outcomes-panel");

  byId("outcome-count-chip").textContent = `${fmt(summary.total_signals_labeled || 0, 0)} rows`;

  const labelHtml = Object.entries(labels).map(([key, value]) => {
    return `<div class="kv"><span>${key}</span><span>${value}</span></div>`;
  }).join("");

  panel.innerHTML = `
    <div class="kv"><span>Total labeled</span><span>${fmt(summary.total_signals_labeled || 0, 0)}</span></div>
    <div class="kv"><span>Avg close return</span><span>${pct(summary.average_close_return_pct)}</span></div>
    <div class="kv"><span>Return observations</span><span>${fmt(summary.return_observation_count || 0, 0)}</span></div>
    ${labelHtml || `<p class="muted">No outcome labels yet.</p>`}
  `;
}

function qualityLabel(row) {
  const q = row.advanced_quality || {};
  const score = q.advanced_quality_score;
  const status = row.quality_gate_status || q.quality_gate_status;
  if (!status && score === undefined) return "N/A";
  return `${status || "QUALITY"} ${score !== undefined ? fmt(score) : ""}`.trim();
}

function marketGuardLabel(row) {
  const g = row.market_guard || {};
  if (!g.halt_luld_status) return "N/A";
  return `${g.halt_luld_status} ${g.halt_luld_proxy_score !== undefined ? fmt(g.halt_luld_proxy_score) : ""}`.trim();
}

function newsLabel(row) {
  const n = row.alpaca_news || {};
  if (!n || typeof n !== "object") return "N/A";
  const count = n.news_count || 0;
  const score = n.news_catalyst_score || 0;
  if (!count) return "No News";
  return `${count} / ${score}`;
}

function finraLabel(row) {
  const candidates = [
    row.finra_short_pressure,
    row.short_pressure,
    row.finra,
    row.short_pressure_label
  ];
  for (const item of candidates) {
    if (!item) continue;
    if (typeof item === "string") return item;
    if (typeof item === "object") return item.pressure_label || item.label || item.short_pressure_label || "Loaded";
  }
  return "N/A";
}

function secLabel(row) {
  const candidates = [
    row.sec_catalyst,
    row.sec,
    row.catalyst,
    row.sec_flag
  ];
  for (const item of candidates) {
    if (!item) continue;
    if (typeof item === "string") return item;
    if (typeof item === "object") return item.flag || item.catalyst_flag || item.latest_form || item.risk_flag || "Loaded";
  }
  return "N/A";
}

function filteredSignals() {
  const term = byId("search-input").value.trim().toUpperCase();
  const status = byId("status-filter").value;

  return state.signals.filter(row => {
    const ticker = String(row.ticker || "").toUpperCase();
    const rowStatus = row.status || "UNKNOWN";
    const matchesTerm = !term || ticker.includes(term);
    const matchesStatus = status === "ALL" || rowStatus === status;
    return matchesTerm && matchesStatus;
  });
}

function renderSignalsTable() {
  const tbody = byId("signals-table");
  const rows = filteredSignals();

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="13">No matching signals.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(row => {
    const status = row.status || row.signal || "UNKNOWN";
    return `
      <tr>
        <td><strong>${row.ticker || "N/A"}</strong></td>
        <td><span class="chip ${chipClass(status)}">${status}</span></td>
        <td>${fmt(row.score)}</td>
        <td>${money(row.price)}</td>
        <td>${fmt(row.relative_volume)}</td>
        <td>${pct(row.vwap_distance_percent ?? row.vwap_distance_pct)}</td>
        <td>${fmt(row.risk_reward)}</td>
        <td>${secLabel(row)}</td>
        <td>${finraLabel(row)}</td>
        <td>${newsLabel(row)}</td>
        <td>${qualityLabel(row)}</td>
        <td>${marketGuardLabel(row)}</td>
        <td class="reason">${row.trade_gate_summary || row.reason || (row.no_trade_reasons || []).join(", ") || "N/A"}</td>
      </tr>
    `;
  }).join("");
}

function renderHealth() {
  const panel = byId("health-panel");
  const loaded = state.health.filter(item => item.ok);

  if (!loaded.length) {
    panel.innerHTML = `<p class="muted">No health files loaded yet.</p>`;
    return;
  }

  panel.innerHTML = loaded.map(item => {
    const data = item.data || {};
    return `
      <div class="kv"><span>${item.path.split("/").pop()}</span><span>${data.status || "Loaded"}</span></div>
    `;
  }).join("");
}

function renderQuality() {
  const panel = byId("quality-panel");

  const qualities = {};
  for (const row of state.signals) {
    const q = row.candidate_quality || (row.data_quality || {}).quality || "UNKNOWN";
    qualities[q] = (qualities[q] || 0) + 1;
  }

  const html = Object.entries(qualities).map(([key, value]) => {
    return `<div class="kv"><span>${key}</span><span>${value}</span></div>`;
  }).join("");

  panel.innerHTML = html || `<p class="muted">No quality data yet.</p>`;
}

function renderLearning() {
  const payload = state.learning || {};
  const panel = byId("learning-panel");

  const summary = payload.summary || payload.learning_summary || {};
  const rows = payload.rows || payload.history || [];

  panel.innerHTML = `
    <div class="kv"><span>Journal rows</span><span>${fmt(summary.total_rows || rows.length || 0, 0)}</span></div>
    <div class="kv"><span>Trade eligible tracked</span><span>${fmt(summary.trade_eligible || summary.trade_eligible_count || 0, 0)}</span></div>
    <div class="kv"><span>No-trade tracked</span><span>${fmt(summary.no_trade || summary.no_trade_count || 0, 0)}</span></div>
    <div class="kv"><span>Generated</span><span>${payload.generated_at || "N/A"}</span></div>
  `;
}

function renderAll() {
  renderMetrics();
  renderTopSetup();
  renderAdaptiveGuard();
  renderPaperPlan();
  renderOutcomes();
  renderSignalsTable();
  renderHealth();
  renderQuality();
  renderLearning();
}

async function init() {
  const signalResult = await fetchFirst(DATA_PATHS.signals);
  state.signalsPayload = signalResult.data || {};
  state.signalsPayload.__sourcePath = signalResult.path;
  state.signals = normalizeSignals(state.signalsPayload);

  state.health = await fetchHealth();
  state.adaptiveGuard = await fetchOptional(DATA_PATHS.adaptiveGuard);
  state.paperPlan = await fetchOptional(DATA_PATHS.paperPlan);
  state.outcomes = await fetchOptional(DATA_PATHS.outcomes);
  state.learning = await fetchOptional(DATA_PATHS.learning);
  state.realMoneyReadiness = await fetchOptional(DATA_PATHS.realMoneyReadiness);
  state.slippage = await fetchOptional(DATA_PATHS.slippage);
  state.quality = await fetchOptional(DATA_PATHS.quality);

  renderAll();

  byId("search-input").addEventListener("input", renderSignalsTable);
  byId("status-filter").addEventListener("change", renderSignalsTable);
}

init().catch(err => {
  console.error(err);
  byId("global-status").textContent = "Dashboard error";
  byId("global-status").className = "status-pill chip red";
  byId("signals-table").innerHTML = `<tr><td colspan="13">Dashboard failed to load: ${err.message}</td></tr>`;
});

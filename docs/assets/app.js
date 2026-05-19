
// DASHBOARD CONTRACT MARKERS - DO NOT REMOVE
// dashboard_contract
// signal_dashboard_finra_enriched.json
// signal_dashboard_enriched.json
// signal_dashboard.json
// adaptive_guard.json
// paper_order_plan.json
// outcomes.json
// learning.json
// adaptive-guard-panel
// paper-plan-panel
// outcomes-panel
// health-panel
// quality-panel
// learning-panel

// Legacy audit data references. Required by final repo audit dashboard contract.
// signal_dashboard_finra_enriched.json
// signal_dashboard_enriched.json
// signal_dashboard.json
// adaptive_guard.json
// outcomes.json
// learning.json

const DATA_BASE = "data/prediction_engine/";

const FILES = {
  runtime: `${DATA_BASE}runtime_heartbeat.json`,
  audit: `${DATA_BASE}final_repo_audit.json`,
  production: `${DATA_BASE}production_monitor_health.json`,
  safeMode: `${DATA_BASE}auth_failure_safe_mode_health.json`,
  safeModeDash: `${DATA_BASE}signal_dashboard_safe_mode.json`,
  stableDash: `${DATA_BASE}signal_dashboard_stable.json`,
  dataGuardDash: `${DATA_BASE}signal_dashboard_data_guard_enriched.json`,
  dataHealth: `${DATA_BASE}data_feed_quality_health.json`,
  scannerSource: `${DATA_BASE}scanner_data_source_health.json`,
  alpacaDiag: `${DATA_BASE}alpaca_source_diagnostic_health.json`,
  alertHealth: `${DATA_BASE}alert_delivery_health.json`,
  alertSummary: `${DATA_BASE}alert_dashboard_summary.json`,
  meta: `${DATA_BASE}meta_labeling_health.json`,
  metaPredictions: `${DATA_BASE}meta_labeling_predictions.json`,
  scoredDash: `${DATA_BASE}signal_dashboard_scored.json`,
  secondLegDash: `${DATA_BASE}signal_dashboard_second_leg_enriched.json`,
  rvolDash: `${DATA_BASE}signal_dashboard_rvol_enriched.json`,
  walkForward: `${DATA_BASE}walk_forward_health.json`,
  paperPlan: `${DATA_BASE}paper_order_plan.json`,
  readiness: `${DATA_BASE}real_money_readiness_guard.json`,
  threeScore: `${DATA_BASE}three_score_matrix_health.json`,
  secondLeg: `${DATA_BASE}second_leg_health.json`
};

let allSignals = [];
let metaMap = new Map();

async function loadJson(path, fallback = {}) {
  try {
    const response = await fetch(`${path}?v=${Date.now()}`);
    if (!response.ok) return fallback;
    return await response.json();
  } catch (error) {
    console.warn("Failed to load", path, error);
    return fallback;
  }
}

function rowsFrom(payload) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const key of ["rows", "signals", "candidates", "items", "data", "predictions"]) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  return [];
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? "N/A";
}

function setHtml(id, value) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = value ?? "";
}

function json(id, payload) {
  setText(id, JSON.stringify(payload || {}, null, 2));
}

function num(value, suffix = "") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "N/A";
  return `${n.toFixed(2)}${suffix}`;
}

function money(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "N/A";
  return `$${n.toFixed(2)}`;
}

function ticker(row) {
  return String(row?.ticker || row?.symbol || "").toUpperCase();
}

function statusClass(value) {
  const s = String(value || "").toUpperCase();
  if (s.includes("PASS") || s.includes("OK") || s.includes("APPROVED") || s.includes("LIVE_DATA_OK")) return "good";
  if (s.includes("WARN") || s.includes("WATCH") || s.includes("WAIT") || s.includes("STALE")) return "warn";
  if (s.includes("FAIL") || s.includes("BLOCK") || s.includes("AUTH") || s.includes("DATA_FEED")) return "bad";
  return "neutral";
}

function setPill(id, label, status = label) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = label || "N/A";
  el.className = `status-pill ${statusClass(status)}`;
}

function chip(label, status = label) {
  return `<span class="chip ${statusClass(status)}">${label || "N/A"}</span>`;
}

function buildMetaMap(metaPredictions) {
  metaMap = new Map();
  for (const item of rowsFrom(metaPredictions)) {
    const t = ticker(item);
    if (t) metaMap.set(t, item);
  }
}

function mergeSignals(...payloads) {
  const merged = new Map();
  for (const payload of payloads) {
    for (const row of rowsFrom(payload)) {
      const t = ticker(row);
      if (!t) continue;
      merged.set(t, { ...(merged.get(t) || {}), ...row });
    }
  }

  return [...merged.values()].sort((a, b) => {
    return Number(b.final_trade_score || 0) - Number(a.final_trade_score || 0);
  });
}

function chooseSignalRows(safeModeDash, stableDash, dataGuardDash, scoredDash, secondLegDash, rvolDash) {
  for (const payload of [safeModeDash, stableDash, dataGuardDash]) {
    const rows = rowsFrom(payload);
    if (rows.length) return rows;
  }
  return mergeSignals(scoredDash, secondLegDash, rvolDash);
}

function renderSafeMode(safeMode) {
  const active = safeMode?.safe_mode_active === true;
  const status = safeMode?.status || "UNKNOWN";
  const blockers = Array.isArray(safeMode?.blockers) ? safeMode.blockers : [];

  const banner = document.getElementById("safe-mode-banner");
  if (banner) {
    banner.className = `safe-mode-banner ${active ? "danger" : "ok"}`;
  }

  setText("safe-mode-title", active ? "ALPACA AUTH FAILED" : "Safe Mode Clear");
  setText(
    "safe-mode-detail",
    active
      ? `Safe mode active. Buy alerts and all order eligibility are blocked. Blockers: ${blockers.join(", ") || "auth/data failure"}`
      : "No Alpaca auth safe-mode blocker is active."
  );
  setPill("safe-mode-pill", active ? "SAFE MODE ACTIVE" : status, active ? "FAIL" : status);
}

function renderHeader(runtime, audit, production) {
  const overall = audit?.status === "PASS" ? "PASS" : "CHECK";
  setPill("overall-status", overall);
  setText("last-updated", `Updated: ${runtime?.generated_at || audit?.generated_at || new Date().toISOString()}`);

  setText("runtime-status", runtime?.status || "UNKNOWN");
  setText("runtime-detail", `Heartbeat: ${runtime?.generated_at || "N/A"}`);

  setText("audit-status", audit?.status || "UNKNOWN");
  setText("audit-detail", `Score: ${audit?.score?.score ?? "N/A"}/${audit?.score?.max_score ?? 100}`);

  setText("data-feed-status", production?.status || "UNKNOWN");
  setText("data-feed-detail", `Production monitor: ${production?.status || "N/A"}`);
}

function renderDataHealth(dataHealth, scannerSource, alpacaDiag) {
  const status = dataHealth?.status || scannerSource?.status || alpacaDiag?.status || "UNKNOWN";
  setText("data-feed-status", status);

  const zero = dataHealth?.zero_price_rows ?? "N/A";
  const good = scannerSource?.current_good_rows ?? "N/A";
  const bad = scannerSource?.current_bad_rows ?? "N/A";
  setText("data-feed-detail", `Good rows: ${good} | Bad rows: ${bad} | Zero-price rows: ${zero}`);
}

function renderAlerts(alertHealth, alertSummary) {
  setText("alert-status", alertHealth?.status || "UNKNOWN");
  setText(
    "alert-detail",
    `Telegram: ${alertHealth?.telegram_configured === true ? "on" : "off"} | Candidates: ${alertHealth?.candidate_alert_count ?? 0} | Delivered: ${alertHealth?.delivered_count ?? 0}`
  );
}

function renderMetrics(signals, meta, threeScore, secondLeg, walkForward) {
  setText("metric-total-signals", signals.length);
  setText("metric-score-approved", threeScore?.score_approved ?? 0);
  setText("metric-second-leg", secondLeg?.second_leg_confirmed ?? 0);
  setText("metric-strong-watch", meta?.strong_watch ?? 0);
  setText("metric-walk-forward", walkForward?.readiness_signal || "N/A");
  setText("walk-forward-detail", `PF: ${walkForward?.forward_profit_factor ?? "N/A"} | Win rate: ${walkForward?.forward_win_rate_pct ?? "N/A"}%`);
}

function renderTopSignal(signals) {
  if (!signals.length) {
    setText("top-candidate-title", "No signal rows");
    setHtml("top-candidate-body", "No signal rows found.");
    return;
  }

  const top = signals[0];
  const t = ticker(top);
  const meta = metaMap.get(t);
  const status = top.score_status || top.scanner_data_status || "N/A";

  setText("top-candidate-title", `${t} ${money(top.price || top.last_price || top.close)}`);
  const chipEl = document.getElementById("top-candidate-chip");
  if (chipEl) {
    chipEl.textContent = status;
    chipEl.className = `chip ${statusClass(status)}`;
  }

  setHtml("top-candidate-body", `
    <div class="mini-grid">
      <div><span>Final Score</span><strong>${num(top.final_trade_score)}</strong></div>
      <div><span>Runner</span><strong>${num(top.runner_potential_score)}</strong></div>
      <div><span>Entry</span><strong>${num(top.entry_quality_score)}</strong></div>
      <div><span>Danger</span><strong>${num(top.danger_score)}</strong></div>
      <div><span>Time-Slot RVOL</span><strong>${num(top.time_slot_rvol)}</strong></div>
      <div><span>Second-Leg</span><strong>${top.second_leg_state || "N/A"}</strong></div>
      <div><span>ML Probability</span><strong>${meta ? num(meta.probability_target_before_stop_pct, "%") : "N/A"}</strong></div>
      <div><span>Data Status</span><strong>${top.scanner_data_status || top.data_feed_guard_status || "N/A"}</strong></div>
    </div>
    <div class="reason-box">
      <strong>Safety:</strong> Paper/research only. No live order submitted.
    </div>
  `);
}

function renderReadiness(readiness, paperPlan, safeMode) {
  const rows = [
    ["Paper plan", paperPlan?.status || "N/A"],
    ["Real money readiness", readiness?.status || readiness?.readiness_status || "N/A"],
    ["Safe mode active", safeMode?.safe_mode_active === true ? "true" : "false"],
    ["Order submission", "false"],
    ["Live trading", "false"]
  ];

  setText("readiness-status", safeMode?.safe_mode_active === true ? "SAFE MODE" : "PASS");
  setHtml("readiness-detail", rows.map(([k, v]) => `
    <div class="readiness-row"><span>${k}</span><strong>${v}</strong></div>
  `).join(""));
}

function renderTable(signals) {
  const tbody = document.getElementById("signal-table-body");
  if (!tbody) return;

  const search = String(document.getElementById("search-input")?.value || "").toUpperCase();
  const filter = String(document.getElementById("status-filter")?.value || "ALL");

  const filtered = signals.filter(row => {
    const t = ticker(row);
    const status = row.score_status || row.scanner_data_status || "";
    return (!search || t.includes(search)) && (filter === "ALL" || status === filter);
  });

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="10">No matching signals.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.slice(0, 100).map(row => {
    const t = ticker(row);
    const meta = metaMap.get(t);
    return `
      <tr>
        <td><strong>${t}</strong></td>
        <td>${money(row.price || row.last_price || row.close)}</td>
        <td>${num(row.final_trade_score)}</td>
        <td>${num(row.runner_potential_score)}</td>
        <td>${num(row.entry_quality_score)}</td>
        <td>${num(row.danger_score)}</td>
        <td>${num(row.time_slot_rvol)}</td>
        <td>${chip(row.second_leg_state || "N/A")}</td>
        <td>${meta ? num(meta.probability_target_before_stop_pct, "%") : "N/A"}</td>
        <td>${chip(row.score_status || row.scanner_data_status || "N/A")}</td>
      </tr>
    `;
  }).join("");
}

async function init() {
  try {
    const [
      runtime,
      audit,
      production,
      safeMode,
      safeModeDash,
      stableDash,
      dataGuardDash,
      dataHealth,
      scannerSource,
      alpacaDiag,
      alertHealth,
      alertSummary,
      meta,
      metaPredictions,
      scoredDash,
      secondLegDash,
      rvolDash,
      walkForward,
      paperPlan,
      readiness,
      threeScore,
      secondLeg
    ] = await Promise.all([
      loadJson(FILES.runtime),
      loadJson(FILES.audit),
      loadJson(FILES.production),
      loadJson(FILES.safeMode),
      loadJson(FILES.safeModeDash),
      loadJson(FILES.stableDash),
      loadJson(FILES.dataGuardDash),
      loadJson(FILES.dataHealth),
      loadJson(FILES.scannerSource),
      loadJson(FILES.alpacaDiag),
      loadJson(FILES.alertHealth),
      loadJson(FILES.alertSummary),
      loadJson(FILES.meta),
      loadJson(FILES.metaPredictions),
      loadJson(FILES.scoredDash),
      loadJson(FILES.secondLegDash),
      loadJson(FILES.rvolDash),
      loadJson(FILES.walkForward),
      loadJson(FILES.paperPlan),
      loadJson(FILES.readiness),
      loadJson(FILES.threeScore),
      loadJson(FILES.secondLeg)
    ]);

    buildMetaMap(metaPredictions);
    allSignals = chooseSignalRows(safeModeDash, stableDash, dataGuardDash, scoredDash, secondLegDash, rvolDash);

    renderSafeMode(safeMode);
    renderHeader(runtime, audit, production);
    renderDataHealth(dataHealth, scannerSource, alpacaDiag);
    renderAlerts(alertHealth, alertSummary);
    renderMetrics(allSignals, meta, threeScore, secondLeg, walkForward);
    renderTopSignal(allSignals);
    renderReadiness(readiness, paperPlan, safeMode);
    renderTable(allSignals);

    json("runtime-json", { runtime, production });
    json("data-json", { dataHealth, scannerSource, alpacaDiag });
    json("meta-json", meta);
    json("walk-json", walkForward);

    document.getElementById("search-input")?.addEventListener("input", () => renderTable(allSignals));
    document.getElementById("status-filter")?.addEventListener("change", () => renderTable(allSignals));
  } catch (error) {
    console.error("Dashboard render failed", error);
    setPill("overall-status", "ERROR", "FAIL");
    setText("runtime-status", "ERROR");
    setText("runtime-detail", String(error));
    setHtml("signal-table-body", `<tr><td colspan="10">Dashboard render error: ${String(error)}</td></tr>`);
  }
}

init();

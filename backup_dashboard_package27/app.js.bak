
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
  scored: `${DATA_BASE}signal_dashboard_scored.json`,
  secondLegDash: `${DATA_BASE}signal_dashboard_second_leg_enriched.json`,
  rvolDash: `${DATA_BASE}signal_dashboard_rvol_enriched.json`,
  threeScore: `${DATA_BASE}three_score_matrix_health.json`,
  secondLeg: `${DATA_BASE}second_leg_health.json`,
  rvol: `${DATA_BASE}time_slot_rvol_health.json`,
  walkForward: `${DATA_BASE}walk_forward_health.json`,
  meta: `${DATA_BASE}meta_labeling_health.json`,
  metaPredictions: `${DATA_BASE}meta_labeling_predictions.json`,
  readiness: `${DATA_BASE}real_money_readiness_guard.json`,
  paperPlan: `${DATA_BASE}paper_order_plan.json`
};

let allSignals = [];
let metaMap = new Map();

async function loadJson(path, fallback = null) {
  try {
    const response = await fetch(`${path}?v=${Date.now()}`);
    if (!response.ok) return fallback;
    return await response.json();
  } catch (error) {
    return fallback;
  }
}

function rowsFrom(payload) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];

  for (const key of ["rows", "signals", "candidates", "items", "data"]) {
    if (Array.isArray(payload[key])) return payload[key];
  }

  return [];
}

function text(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? "N/A";
}

function html(id, value) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = value ?? "";
}

function fmt(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "N/A";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return `${num.toFixed(2)}${suffix}`;
}

function fmtMoney(value) {
  if (value === null || value === undefined || value === "") return "N/A";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return `$${num.toFixed(2)}`;
}

function getTicker(row) {
  return String(row.ticker || row.symbol || "").toUpperCase();
}

function getNested(obj, path) {
  if (!obj || typeof obj !== "object") return undefined;
  return path.split(".").reduce((cur, key) => {
    if (!cur || typeof cur !== "object") return undefined;
    return cur[key];
  }, obj);
}

function pick(row, keys, fallback = null) {
  for (const key of keys) {
    const value = key.includes(".") ? getNested(row, key) : row[key];
    if (value !== null && value !== undefined && value !== "") return value;
  }
  return fallback;
}

function statusClass(status) {
  const value = String(status || "").toUpperCase();

  if (value.includes("PASS") || value.includes("OK") || value.includes("APPROVED") || value.includes("CONFIRMED")) {
    return "good";
  }

  if (value.includes("WATCH") || value.includes("WAIT") || value.includes("WARN") || value.includes("CAUTION")) {
    return "warn";
  }

  if (value.includes("FAIL") || value.includes("BLOCK") || value.includes("REJECT") || value.includes("NOT_READY")) {
    return "bad";
  }

  return "neutral";
}

function chip(label, status = "") {
  return `<span class="chip ${statusClass(status || label)}">${label}</span>`;
}

function setPill(id, label, status) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = label;
  el.className = `status-pill ${statusClass(status || label)}`;
}

function renderOverall(runtime, audit) {
  const runtimeStatus = runtime?.status || "UNKNOWN";
  const auditStatus = audit?.status || "UNKNOWN";

  const overall = runtimeStatus === "PASS" && auditStatus === "PASS" ? "PASS" : "CHECK";
  setPill("overall-status", overall, overall);

  const updated = runtime?.generated_at || audit?.generated_at || new Date().toISOString();
  text("last-updated", `Updated: ${updated}`);
}

function renderRuntime(runtime) {
  text("runtime-status", runtime?.status || "UNKNOWN");
  text(
    "runtime-detail",
    `Alpaca keys: ${runtime?.has_alpaca_keys === true ? "yes" : "no"} | SEC user agent: ${runtime?.has_sec_user_agent === true ? "yes" : "no"}`
  );
}

function renderAudit(audit) {
  text("audit-status", audit?.status || "UNKNOWN");

  const score = audit?.score?.score ?? "N/A";
  const max = audit?.score?.max_score ?? 100;
  const blockers = audit?.score?.blockers || [];

  text("audit-detail", `Score: ${score}/${max} | Blockers: ${blockers.length}`);
}

function renderSafety(runtime, meta) {
  const paper = runtime?.paper_order_submission_enabled === true;
  const live = runtime?.live_trading_enabled === true;
  const modelOverride = meta?.model_can_override_risk_gate === true;

  if (!paper && !live && !modelOverride) {
    text("safety-status", "SAFE");
    text("safety-detail", "Paper submission off. Live trading off. Model cannot override risk.");
    return;
  }

  text("safety-status", "REVIEW");
  text("safety-detail", `Paper: ${paper} | Live: ${live} | Model override: ${modelOverride}`);
}

function renderMeta(meta) {
  text("meta-status", meta?.status || "UNKNOWN");
  text(
    "meta-detail",
    `Rows: ${meta?.rows ?? 0} | Strong watch: ${meta?.strong_watch ?? 0} | Watch: ${meta?.watch ?? 0}`
  );
}

function renderMetrics(threeScore, secondLeg, meta, walkForward, signalRows) {
  text("metric-signals", signalRows.length);
  text("metric-score-approved", threeScore?.score_approved ?? threeScore?.counts?.score_approved ?? 0);
  text("metric-second-leg", secondLeg?.second_leg_confirmed ?? 0);
  text("metric-strong-watch", meta?.strong_watch ?? 0);

  const wfSignal = walkForward?.readiness_signal || "N/A";
  text("metric-walk-forward", wfSignal);
  text(
    "walk-forward-detail",
    `PF: ${walkForward?.forward_profit_factor ?? "N/A"} | Win rate: ${walkForward?.forward_win_rate_pct ?? "N/A"}%`
  );
}

function buildMetaMap(metaPredictions) {
  metaMap = new Map();
  const predictions = metaPredictions?.predictions || [];

  for (const item of predictions) {
    const ticker = String(item.ticker || "").toUpperCase();
    if (ticker) metaMap.set(ticker, item);
  }
}

function mergeSignalRows(rvolDash, secondLegDash, scoredDash) {
  const rvolRows = rowsFrom(rvolDash);
  const secondRows = rowsFrom(secondLegDash);
  const scoreRows = rowsFrom(scoredDash);

  const merged = new Map();

  for (const sourceRows of [scoreRows, secondRows, rvolRows]) {
    for (const row of sourceRows) {
      const ticker = getTicker(row);
      if (!ticker) continue;

      const previous = merged.get(ticker) || {};
      merged.set(ticker, { ...previous, ...row });
    }
  }

  return Array.from(merged.values()).sort((a, b) => {
    const bScore = Number(b.final_trade_score || 0);
    const aScore = Number(a.final_trade_score || 0);
    return bScore - aScore;
  });
}

function renderTopCandidate(rows) {
  if (!rows.length) {
    text("top-candidate-title", "No candidate");
    html("top-candidate-body", "No signal rows found.");
    return;
  }

  const top = rows[0];
  const ticker = getTicker(top);
  const meta = metaMap.get(ticker);

  const scoreStatus = top.score_status || "N/A";
  const secondState = top.second_leg_state || top.second_leg?.state || "N/A";
  const probability = meta?.probability_target_before_stop_pct;

  text("top-candidate-title", `${ticker || "N/A"} ${fmtMoney(pick(top, ["price", "last_price", "close"], null))}`);
  const chipEl = document.getElementById("top-candidate-chip");
  if (chipEl) {
    chipEl.textContent = scoreStatus;
    chipEl.className = `chip ${statusClass(scoreStatus)}`;
  }

  html("top-candidate-body", `
    <div class="mini-grid">
      <div><span>Final Score</span><strong>${fmt(top.final_trade_score)}</strong></div>
      <div><span>Runner</span><strong>${fmt(top.runner_potential_score)}</strong></div>
      <div><span>Entry</span><strong>${fmt(top.entry_quality_score)}</strong></div>
      <div><span>Danger</span><strong>${fmt(top.danger_score)}</strong></div>
      <div><span>Time-Slot RVOL</span><strong>${fmt(top.time_slot_rvol)}</strong></div>
      <div><span>Second-Leg</span><strong>${secondState}</strong></div>
      <div><span>ML Probability</span><strong>${probability !== undefined ? fmt(probability, "%") : "N/A"}</strong></div>
      <div><span>ML Decision</span><strong>${meta?.model_decision || "N/A"}</strong></div>
    </div>
    <div class="reason-box">
      <strong>Blocks:</strong>
      ${(top.score_blocks || top.second_leg_blocks || []).length ? (top.score_blocks || top.second_leg_blocks || []).join(", ") : "None listed"}
    </div>
  `);
}

function renderReadiness(readiness, paperPlan) {
  const status = readiness?.status || readiness?.readiness_status || "UNKNOWN";
  text("readiness-title", status);

  const items = [
    ["Paper plan", paperPlan?.status || "N/A"],
    ["Real money readiness", status],
    ["Order submission", readiness?.order_submission || false],
    ["Live trading", readiness?.live_trading || false],
    ["Manual approval", readiness?.manual_approval_required ?? "N/A"]
  ];

  html(
    "readiness-body",
    items.map(([label, value]) => `
      <div class="readiness-row">
        <span>${label}</span>
        <strong>${value}</strong>
      </div>
    `).join("")
  );
}

function renderTable(rows) {
  const tbody = document.getElementById("signal-table-body");
  if (!tbody) return;

  const search = String(document.getElementById("search-input")?.value || "").toUpperCase();
  const filter = String(document.getElementById("status-filter")?.value || "ALL");

  const filtered = rows.filter(row => {
    const ticker = getTicker(row);
    const status = row.score_status || "";
    const matchesSearch = !search || ticker.includes(search);
    const matchesFilter = filter === "ALL" || status === filter;
    return matchesSearch && matchesFilter;
  });

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="10">No matching signals.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.slice(0, 100).map(row => {
    const ticker = getTicker(row);
    const meta = metaMap.get(ticker);
    const secondState = row.second_leg_state || row.second_leg?.state || "N/A";
    const status = row.score_status || "N/A";
    const probability = meta?.probability_target_before_stop_pct;

    return `
      <tr>
        <td><strong>${ticker}</strong></td>
        <td>${fmtMoney(pick(row, ["price", "last_price", "close"], null))}</td>
        <td>${fmt(row.final_trade_score)}</td>
        <td>${fmt(row.runner_potential_score)}</td>
        <td>${fmt(row.entry_quality_score)}</td>
        <td>${fmt(row.danger_score)}</td>
        <td>${fmt(row.time_slot_rvol)}</td>
        <td>${chip(secondState, secondState)}</td>
        <td>${probability !== undefined ? fmt(probability, "%") : "N/A"}</td>
        <td>${chip(status, status)}</td>
      </tr>
    `;
  }).join("");
}

function renderJson(id, payload) {
  text(id, JSON.stringify(payload || {}, null, 2));
}

async function init() {
  const [
    runtime,
    audit,
    scoredDash,
    secondLegDash,
    rvolDash,
    threeScore,
    secondLeg,
    rvol,
    walkForward,
    meta,
    metaPredictions,
    readiness,
    paperPlan
  ] = await Promise.all([
    loadJson(FILES.runtime, {}),
    loadJson(FILES.audit, {}),
    loadJson(FILES.scored, {}),
    loadJson(FILES.secondLegDash, {}),
    loadJson(FILES.rvolDash, {}),
    loadJson(FILES.threeScore, {}),
    loadJson(FILES.secondLeg, {}),
    loadJson(FILES.rvol, {}),
    loadJson(FILES.walkForward, {}),
    loadJson(FILES.meta, {}),
    loadJson(FILES.metaPredictions, {}),
    loadJson(FILES.readiness, {}),
    loadJson(FILES.paperPlan, {})
  ]);

  buildMetaMap(metaPredictions);
  allSignals = mergeSignalRows(rvolDash, secondLegDash, scoredDash);

  renderOverall(runtime, audit);
  renderRuntime(runtime);
  renderAudit(audit);
  renderSafety(runtime, meta);
  renderMeta(meta);
  renderMetrics(threeScore, secondLeg, meta, walkForward, allSignals);
  renderTopCandidate(allSignals);
  renderReadiness(readiness, paperPlan);
  renderTable(allSignals);

  renderJson("three-score-json", threeScore);
  renderJson("second-leg-json", secondLeg);
  renderJson("rvol-json", rvol);
  renderJson("walk-forward-json", walkForward);

  document.getElementById("search-input")?.addEventListener("input", () => renderTable(allSignals));
  document.getElementById("status-filter")?.addEventListener("change", () => renderTable(allSignals));
}

init();
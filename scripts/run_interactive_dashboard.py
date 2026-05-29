"""
Interactive Dashboard (Flask backend)
=====================================
Serves the interactive single-page UI at / and JSON endpoints for the
consensus aggregator, pre-breakout scanner, scorecard, and outcomes log.

Run on the VM:
    cd ~/jini && pip3 install flask
    PYTHONPATH=src python3 scripts/run_interactive_dashboard.py
    # browse to http://VM_IP:5050/

Env vars:
    DASHBOARD_PORT  (default 5050)
    DASHBOARD_HOST  (default 0.0.0.0)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

JINI_ROOT  = Path(__file__).resolve().parent.parent
STATE_DIR  = JINI_ROOT / "state"
DOCS_DIR   = JINI_ROOT / "docs"
HTML_FILE  = DOCS_DIR / "interactive.html"
ENGINE2_DOCS = (JINI_ROOT.parent / "engine2" / "docs").resolve()
NOTES_PATH      = STATE_DIR / "user_notes.json"
WATCHLIST_PATH  = STATE_DIR / "user_watchlist.json"

app = Flask(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────────
def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"{path.name}: {e}", **(default if isinstance(default, dict) else {})}


def _now_utc():
    return datetime.now(timezone.utc).isoformat()


# ─── HTML ────────────────────────────────────────────────────────────────
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"]        = "no-cache"
    response.headers["Expires"]       = "0"
    return response


@app.route("/")
def index():
    if HTML_FILE.exists():
        return _no_cache(app.make_response(HTML_FILE.read_text(encoding="utf-8")))
    return ("<h1>interactive.html missing</h1>"
            f"<p>Expected at: <code>{HTML_FILE}</code></p>"), 503


# ─── Engine2 standalone dashboard (static files under ../engine2/docs) ─────
@app.route("/engine2/", defaults={"subpath": "index.html"})
@app.route("/engine2/<path:subpath>")
def engine2_docs(subpath):
    if not ENGINE2_DOCS.exists():
        return (f"<h1>engine2 docs not found</h1><p>Expected at {ENGINE2_DOCS}</p>"), 503
    resp = send_from_directory(ENGINE2_DOCS, subpath)
    # signals.json must never be cached so the dashboard shows fresh scans
    if subpath.endswith(".json"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# ─── Read endpoints ──────────────────────────────────────────────────────
@app.route("/api/consensus")
def api_consensus():
    return jsonify(_read_json(STATE_DIR / "consensus_picks_live.json",
                              {"consensus_picks": [], "vote_table": [],
                               "active_engines": [], "threshold": 2,
                               "engine_weights": {}}))


@app.route("/api/prebreakout")
def api_prebreakout():
    return jsonify(_read_json(STATE_DIR / "prebreakout_candidates.json",
                              {"candidates": []}))


@app.route("/api/swing")
def api_swing():
    return jsonify(_read_json(STATE_DIR / "swing_candidates.json",
                              {"candidates": []}))


@app.route("/api/scorecard")
def api_scorecard():
    return jsonify(_read_json(STATE_DIR / "consensus_scorecard.json", {}))


@app.route("/api/outcomes")
def api_outcomes():
    path = STATE_DIR / "consensus_outcomes.jsonl"
    if not path.exists():
        return jsonify({"records": []})
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except Exception as e:
        return jsonify({"error": str(e), "records": []}), 500
    records.reverse()  # newest first
    return jsonify({"records": records[:300]})


@app.route("/api/enriched")
def api_enriched():
    """jini's current enriched candidate rows."""
    data = _read_json(STATE_DIR / "prediction_engine" / "v3_enriched_rows.json", [])
    rows = data if isinstance(data, list) else data.get("rows", data.get("candidates", []))
    return jsonify({"rows": rows, "count": len(rows)})


@app.route("/api/health")
def api_health():
    def fresh(p: Path):
        if not p.exists():
            return None
        return round(datetime.now().timestamp() - p.stat().st_mtime, 1)
    return jsonify({
        "now":        _now_utc(),
        "files": {
            "consensus_picks_live.json":      fresh(STATE_DIR / "consensus_picks_live.json"),
            "prebreakout_candidates.json":    fresh(STATE_DIR / "prebreakout_candidates.json"),
            "swing_candidates.json":          fresh(STATE_DIR / "swing_candidates.json"),
            "consensus_outcomes.jsonl":       fresh(STATE_DIR / "consensus_outcomes.jsonl"),
            "consensus_scorecard.json":       fresh(STATE_DIR / "consensus_scorecard.json"),
            "v3_enriched_rows.json":          fresh(STATE_DIR / "prediction_engine" / "v3_enriched_rows.json"),
        },
    })


# ─── Write endpoints ─────────────────────────────────────────────────────
@app.route("/api/notes", methods=["GET", "POST"])
def api_notes():
    if request.method == "GET":
        return jsonify(_read_json(NOTES_PATH, {}))
    body   = request.get_json(force=True, silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    note   = body.get("note", "").strip()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    notes = _read_json(NOTES_PATH, {}) or {}
    if note:
        notes[ticker] = {"note": note, "updated_at": _now_utc()}
    else:
        notes.pop(ticker, None)
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTES_PATH.write_text(json.dumps(notes, indent=2), encoding="utf-8")
    return jsonify({"status": "ok", "ticker": ticker})


@app.route("/api/watchlist", methods=["GET", "POST"])
def api_watchlist():
    if request.method == "GET":
        return jsonify(_read_json(WATCHLIST_PATH, {"tickers": []}))
    body    = request.get_json(force=True, silent=True) or {}
    action  = body.get("action")
    ticker  = (body.get("ticker") or "").strip().upper()
    data    = _read_json(WATCHLIST_PATH, {"tickers": []}) or {"tickers": []}
    tickers = set(data.get("tickers", []))
    if action == "add" and ticker:
        tickers.add(ticker)
    elif action == "remove" and ticker:
        tickers.discard(ticker)
    elif action == "clear":
        tickers.clear()
    data["tickers"] = sorted(tickers)
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return jsonify(data)


@app.route("/api/outcome-mark", methods=["POST"])
def api_outcome_mark():
    """Manually flip hit/miss on the most-recent open outcome for a ticker."""
    body   = request.get_json(force=True, silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    hit    = body.get("hit")
    notes  = body.get("notes", "")
    if not ticker or hit is None:
        return jsonify({"error": "ticker and hit required"}), 400

    log_path = STATE_DIR / "consensus_outcomes.jsonl"
    if not log_path.exists():
        return jsonify({"error": "no outcomes log"}), 404

    lines = log_path.read_text(encoding="utf-8").splitlines()
    updated = False
    for i in range(len(lines) - 1, -1, -1):
        if not lines[i].strip():
            continue
        try:
            rec = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if rec.get("ticker") == ticker and rec.get("outcome_hit_target") is None:
            rec["outcome_hit_target"] = bool(hit)
            rec["outcome_notes"]      = notes
            rec["outcome_filled_at"]  = _now_utc() + "  (manual)"
            lines[i] = json.dumps(rec)
            updated = True
            break
    if not updated:
        return jsonify({"error": "no open outcome for ticker"}), 404
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonify({"status": "ok", "ticker": ticker, "hit": bool(hit)})


# ─── Main ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "5050"))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    print(f"Interactive dashboard at http://{host}:{port}/")
    app.run(host=host, port=port, debug=False)

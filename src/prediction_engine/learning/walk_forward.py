from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


INPUTS = [
    Path("docs/data/prediction_engine/signal_dashboard_rvol_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_second_leg_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard_scored.json"),
    Path("docs/data/prediction_engine/signal_dashboard_quality_enriched.json"),
    Path("docs/data/prediction_engine/signal_dashboard.json"),
]

JOURNAL_INPUTS = [
    Path("docs/data/prediction_engine/signal_journal.json"),
    Path("docs/data/prediction_engine/outcome_labels.json"),
    Path("docs/data/prediction_engine/slippage_fill_tracker.json"),
]

OUT_RESULTS = Path("docs/data/prediction_engine/walk_forward_results.json")
OUT_HEALTH = Path("docs/data/prediction_engine/walk_forward_health.json")
OUT_STATE = Path("state/prediction_engine/walk_forward_results.json")


PARAMETER_GRID = [
    {"name": "fast_scalp", "target_pct": 1.5, "stop_pct": 0.8},
    {"name": "balanced_scalp", "target_pct": 2.0, "stop_pct": 1.0},
    {"name": "base_second_leg", "target_pct": 2.5, "stop_pct": 1.2},
    {"name": "wide_runner", "target_pct": 3.0, "stop_pct": 1.5},
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def rows_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if isinstance(payload, dict):
        for key in ("rows", "signals", "candidates", "items", "data", "journal", "outcomes"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

    return []


def load_best_rows(paths: list[Path]) -> tuple[list[dict[str, Any]], str]:
    for path in paths:
        payload = read_json(path, {})
        rows = rows_from(payload)
        if rows:
            return rows, str(path)

    return [], "none"


def nested(row: dict[str, Any], key: str) -> Any:
    cur: Any = row

    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)

    return cur


def pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = nested(row, key) if "." in key else row.get(key)
        if value is not None:
            return value

    return None


def f(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def symbol(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


def signal_time(row: dict[str, Any]) -> datetime:
    value = pick(
        row,
        "generated_at",
        "timestamp",
        "time",
        "created_at",
        "signal_time",
        "checked_at",
    )
    parsed = parse_time(value)
    return parsed or datetime.now(timezone.utc)


def score_value(row: dict[str, Any]) -> float:
    return f(
        pick(
            row,
            "final_trade_score",
            "three_score_matrix.final_trade_score",
            "advanced_quality.advanced_quality_score",
            "score",
        ),
        0.0,
    ) or 0.0


def setup_type(row: dict[str, Any]) -> str:
    if row.get("second_leg_confirmed") is True:
        return "SECOND_LEG_CONTINUATION"

    value = pick(row, "setup_type", "decision", "status", "score_status")
    return str(value or "UNKNOWN").upper()


def slippage_penalty(row: dict[str, Any]) -> float:
    spread = f(pick(row, "advanced_quality.spread_pct", "spread_pct"), 0.0) or 0.0
    quote_age = f(pick(row, "quote_age_seconds", "quote_age", "age_seconds"), 0.0) or 0.0

    penalty = 0.0

    if spread > 1.0:
        penalty += min(1.0, spread - 1.0)

    if quote_age > 2.0:
        penalty += min(1.0, (quote_age - 2.0) / 5.0)

    return round(penalty, 4)


def infer_outcome_return(row: dict[str, Any], params: dict[str, float]) -> float:
    explicit_return = f(
        pick(
            row,
            "return_pct",
            "realized_return_pct",
            "pnl_pct",
            "outcome.return_pct",
        )
    )
    if explicit_return is not None:
        return explicit_return

    outcome = str(
        pick(
            row,
            "outcome",
            "outcome_label",
            "label",
            "result",
            "exit_reason",
        )
        or ""
    ).upper()

    target = float(params["target_pct"])
    stop = float(params["stop_pct"])
    slip = slippage_penalty(row)

    if any(token in outcome for token in ["TARGET", "WIN", "PROFIT"]):
        return target - slip

    if any(token in outcome for token in ["STOP", "LOSS", "FAILED", "FADED"]):
        return -stop - slip

    # If no actual outcome exists yet, create a conservative proxy from signal quality.
    score = score_value(row)
    danger = f(pick(row, "danger_score", "three_score_matrix.danger_score"), 50.0) or 50.0
    confirmed = bool(row.get("second_leg_confirmed"))

    edge = (score - 70.0) / 30.0
    edge -= danger / 150.0
    if confirmed:
        edge += 0.25

    proxy = edge * target - slip
    return round(max(-stop, min(target, proxy)), 4)


def build_signal_dataset() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dashboard_rows, dashboard_source = load_best_rows(INPUTS)
    journal_rows, journal_source = load_best_rows(JOURNAL_INPUTS)

    rows = journal_rows if journal_rows else dashboard_rows
    source = journal_source if journal_rows else dashboard_source

    dataset = []
    for row in rows:
        item = dict(row)
        item["_symbol"] = symbol(row)
        item["_time"] = signal_time(row).isoformat()
        item["_score"] = score_value(row)
        item["_setup_type"] = setup_type(row)
        item["_slippage_penalty"] = slippage_penalty(row)
        dataset.append(item)

    dataset.sort(key=lambda x: x["_time"])

    meta = {
        "source": source,
        "journal_source": journal_source,
        "dashboard_source": dashboard_source,
        "used_journal": bool(journal_rows),
        "rows": len(dataset),
    }

    return dataset, meta


def split_windows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    if not rows:
        return {"train": [], "embargo": [], "test": []}

    times = [parse_time(row["_time"]) or datetime.now(timezone.utc) for row in rows]
    end = max(times)

    test_start = end - timedelta(days=7)
    embargo_start = test_start - timedelta(minutes=10)
    train_start = embargo_start - timedelta(days=14)

    train = []
    embargo = []
    test = []

    for row in rows:
        dt = parse_time(row["_time"]) or end

        if train_start <= dt < embargo_start:
            train.append(row)
        elif embargo_start <= dt < test_start:
            embargo.append(row)
        elif dt >= test_start:
            test.append(row)

    # If the data is too fresh/small, fall back to deterministic 60/10/30 split.
    if len(train) + len(test) < 5 and rows:
        n = len(rows)
        train_end = max(1, int(n * 0.60))
        embargo_end = max(train_end, int(n * 0.70))

        train = rows[:train_end]
        embargo = rows[train_end:embargo_end]
        test = rows[embargo_end:]

    return {
        "train": train,
        "embargo": embargo,
        "test": test,
    }


def evaluate_rows(rows: list[dict[str, Any]], params: dict[str, float]) -> dict[str, Any]:
    returns = [infer_outcome_return(row, params) for row in rows]

    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None

    win_rate = round(len(wins) / len(returns) * 100, 2) if returns else 0.0
    avg_return = round(statistics.mean(returns), 4) if returns else 0.0
    avg_winner = round(statistics.mean(wins), 4) if wins else 0.0
    avg_loser = round(statistics.mean(losses), 4) if losses else 0.0

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)

    setup_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("_setup_type") or "UNKNOWN")
        setup_counts[key] = setup_counts.get(key, 0) + 1

    return {
        "trade_count": len(rows),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": win_rate,
        "avg_return_pct": avg_return,
        "avg_winner_pct": avg_winner,
        "avg_loser_pct": avg_loser,
        "gross_profit_pct": round(gross_profit, 4),
        "gross_loss_pct": round(gross_loss, 4),
        "profit_factor": profit_factor,
        "max_drawdown_pct": round(max_drawdown, 4),
        "setup_counts": setup_counts,
    }


def choose_best_parameter(train_rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = []

    for params in PARAMETER_GRID:
        result = evaluate_rows(train_rows, params)
        score = (
            (result["profit_factor"] or 0.0) * 40
            + result["win_rate_pct"] * 0.4
            + result["avg_return_pct"] * 10
            + result["max_drawdown_pct"]
        )

        results.append({
            "params": params,
            "train_metrics": result,
            "selection_score": round(score, 4),
        })

    results.sort(key=lambda x: x["selection_score"], reverse=True)

    if not results:
        return {
            "params": PARAMETER_GRID[2],
            "train_metrics": evaluate_rows([], PARAMETER_GRID[2]),
            "selection_score": 0,
        }

    return results[0]


def export() -> dict[str, Any]:
    dataset, meta = build_signal_dataset()
    windows = split_windows(dataset)

    best = choose_best_parameter(windows["train"])
    test_metrics = evaluate_rows(windows["test"], best["params"])

    generated_at = now()

    result = {
        "schema_version": "walk_forward_results_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "mode": "slippage_aware_walk_forward",
        "source": meta,
        "windowing": {
            "train_days": 14,
            "embargo_minutes": 10,
            "test_days": 7,
            "train_rows": len(windows["train"]),
            "embargo_rows": len(windows["embargo"]),
            "test_rows": len(windows["test"]),
        },
        "parameter_grid": PARAMETER_GRID,
        "best_train_selection": best,
        "forward_test_metrics": test_metrics,
        "readiness_signal": readiness_signal(test_metrics),
        "safety": {
            "order_submission": False,
            "live_trading": False,
            "purpose": "Walk-forward research only. Does not submit orders.",
            "disclaimer": "Research and paper-trading validation only. Not financial advice.",
        },
    }

    health = {
        "schema_version": "walk_forward_health_v1",
        "generated_at": generated_at,
        "status": "PASS",
        "rows": len(dataset),
        "train_rows": len(windows["train"]),
        "test_rows": len(windows["test"]),
        "selected_params": best["params"],
        "forward_profit_factor": test_metrics["profit_factor"],
        "forward_win_rate_pct": test_metrics["win_rate_pct"],
        "readiness_signal": result["readiness_signal"],
        "order_submission": False,
        "live_trading": False,
    }

    write_json(OUT_RESULTS, result)
    write_json(OUT_STATE, result)
    write_json(OUT_HEALTH, health)

    return {
        "status": "PASS",
        "rows": len(dataset),
        "selected_params": best["params"],
        "results_path": str(OUT_RESULTS),
        "health_path": str(OUT_HEALTH),
    }


def readiness_signal(metrics: dict[str, Any]) -> str:
    trade_count = int(metrics.get("trade_count") or 0)
    win_rate = float(metrics.get("win_rate_pct") or 0.0)
    profit_factor = metrics.get("profit_factor")
    drawdown = float(metrics.get("max_drawdown_pct") or 0.0)

    if trade_count < 20:
        return "INSUFFICIENT_SAMPLE"

    if profit_factor is not None and profit_factor >= 1.25 and win_rate >= 45 and drawdown > -10:
        return "PROMISING_PAPER_ONLY"

    if profit_factor is not None and profit_factor >= 1.0 and win_rate >= 40:
        return "WATCH_MORE_DATA"

    return "NOT_READY"


def main() -> None:
    print(json.dumps(export(), indent=2))


if __name__ == "__main__":
    main()
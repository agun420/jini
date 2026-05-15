from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SIGNAL_INPUT_CANDIDATES = [
    Path('docs/data/prediction_engine/signal_dashboard_market_guard_enriched.json'),
    Path('docs/data/prediction_engine/signal_dashboard_quality_enriched.json'),
    Path('docs/data/prediction_engine/signal_dashboard_news_enriched.json'),
    Path('docs/data/prediction_engine/signal_dashboard_finra_enriched.json'),
    Path('docs/data/prediction_engine/signal_dashboard_enriched.json'),
    Path('docs/data/prediction_engine/signal_dashboard.json'),
]

FREE_SCANNER_CANDIDATES = [
    Path('docs/data/prediction_engine/free_scanner_finra_enriched.json'),
    Path('docs/data/prediction_engine/free_scanner_enriched.json'),
    Path('docs/data/prediction_engine/free_scanner.json'),
]

JOURNAL_PATH = Path('state/prediction_engine/signal_history.json')
LEARNING_STATE_PATH = Path('state/prediction_engine/learning_state.json')
LEARNING_DASHBOARD_PATH = Path('docs/data/prediction_engine/learning.json')
HEALTH_PATH = Path('docs/data/prediction_engine/signal_journal_health.json')

MAX_JOURNAL_ROWS = 5000


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding='utf-8').strip()
        return json.loads(raw) if raw else default
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding='utf-8')


def first_existing(paths: List[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists():
            return path
    return None


def normalize_symbol(value: Any) -> str:
    return str(value or '').upper().strip()


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except Exception:
        return default


def load_signal_rows() -> Dict[str, Any]:
    source_path = first_existing(SIGNAL_INPUT_CANDIDATES)
    if not source_path:
        return {
            'source_path': None,
            'rows': [],
            'source_payload': {},
        }

    payload = read_json(source_path, {})
    rows = payload.get('rows') if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []

    return {
        'source_path': str(source_path),
        'rows': [row for row in rows if isinstance(row, dict)],
        'source_payload': payload if isinstance(payload, dict) else {},
    }


def load_free_scanner_summary() -> Dict[str, Any]:
    path = first_existing(FREE_SCANNER_CANDIDATES)
    if not path:
        return {}
    payload = read_json(path, {})
    return payload if isinstance(payload, dict) else {}


def make_signal_key(row: Dict[str, Any], generated_at: str) -> str:
    ticker = normalize_symbol(row.get('ticker'))
    status = str(row.get('status') or row.get('signal') or 'UNKNOWN')
    score = safe_float(row.get('score'), 0.0) or 0.0
    price = safe_float(row.get('price'), 0.0) or 0.0
    # Keep one record per ticker/status/run. Later packages will add outcome snapshots.
    return f'{generated_at}|{ticker}|{status}|{score:.2f}|{price:.4f}'


def classify_bucket(score: Optional[float]) -> str:
    if score is None:
        return 'UNKNOWN'
    if score >= 90:
        return '90_100'
    if score >= 80:
        return '80_89'
    if score >= 70:
        return '70_79'
    if score >= 60:
        return '60_69'
    if score >= 40:
        return '40_59'
    return '0_39'


def build_journal_record(row: Dict[str, Any], run_generated_at: str, source_path: Optional[str]) -> Dict[str, Any]:
    ticker = normalize_symbol(row.get('ticker'))
    score = safe_float(row.get('score'), None)
    status = str(row.get('status') or 'UNKNOWN')
    no_trade_reasons = row.get('no_trade_reasons') if isinstance(row.get('no_trade_reasons'), list) else []

    was_trade_eligible = status == 'TRADE_ELIGIBLE'
    was_paper_order_submitted = False

    skip_reason = None
    if not was_trade_eligible:
        skip_reason = ';'.join(str(x) for x in no_trade_reasons) or status
    else:
        # Package 4 still does not submit orders.
        skip_reason = 'paper_execution_not_enabled_in_package_4'

    return {
        'journal_schema_version': 'signal_history_v1',
        'journaled_at': now_utc_iso(),
        'run_generated_at': run_generated_at,
        'source_path': source_path,
        'signal_key': make_signal_key(row, run_generated_at),
        'ticker': ticker,
        'status': status,
        'signal': row.get('signal'),
        'score': score,
        'score_bucket': classify_bucket(score),
        'price': safe_float(row.get('price'), None),
        'entry': safe_float(row.get('entry'), None),
        'stop': safe_float(row.get('stop'), None),
        'target': safe_float(row.get('target'), None),
        'risk_reward': safe_float(row.get('risk_reward'), None),
        'relative_volume': safe_float(row.get('relative_volume'), None),
        'day_move_percent': safe_float(row.get('day_move_percent'), None),
        'gap_pct': safe_float(row.get('gap_pct'), None),
        'vwap': safe_float(row.get('vwap'), None),
        'vwap_distance_percent': safe_float(row.get('vwap_distance_percent'), None),
        'volume_acceleration': safe_float(row.get('volume_acceleration'), None),
        'trend_state': row.get('trend_state'),
        'candidate_quality': row.get('candidate_quality'),
        'data_quality': row.get('data_quality'),
        'sec_context': row.get('sec_context') or row.get('sec_catalyst'),
        'finra_context': row.get('finra_context') or row.get('short_pressure'),
        'trade_gate_summary': row.get('trade_gate_summary'),
        'no_trade_reasons': no_trade_reasons,
        'was_trade_eligible': was_trade_eligible,
        'was_paper_order_submitted': was_paper_order_submitted,
        'skip_reason': skip_reason,
        'future_outcome': {
            'status': 'PENDING',
            'future_30m_return_pct': None,
            'future_60m_return_pct': None,
            'hit_target_before_stop': None,
            'notes': 'Outcome labeling is added in a later package.',
        },
    }


def append_signal_history() -> Dict[str, Any]:
    loaded = load_signal_rows()
    rows = loaded['rows']
    source_path = loaded['source_path']
    source_payload = loaded['source_payload']
    scanner_summary = load_free_scanner_summary()

    run_generated_at = str(
        source_payload.get('generated_at')
        or scanner_summary.get('generated_at')
        or now_utc_iso()
    )

    existing_payload = read_json(JOURNAL_PATH, {'schema_version': 'signal_history_v1', 'rows': []})
    existing_rows = existing_payload.get('rows') if isinstance(existing_payload, dict) else []
    if not isinstance(existing_rows, list):
        existing_rows = []

    existing_keys = {str(row.get('signal_key')) for row in existing_rows if isinstance(row, dict)}

    new_records = []
    for row in rows:
        ticker = normalize_symbol(row.get('ticker'))
        if not ticker:
            continue
        record = build_journal_record(row, run_generated_at, source_path)
        if record['signal_key'] in existing_keys:
            continue
        new_records.append(record)
        existing_keys.add(record['signal_key'])

    all_rows = existing_rows + new_records
    if len(all_rows) > MAX_JOURNAL_ROWS:
        all_rows = all_rows[-MAX_JOURNAL_ROWS:]

    journal_payload = {
        'schema_version': 'signal_history_v1',
        'updated_at': now_utc_iso(),
        'max_rows': MAX_JOURNAL_ROWS,
        'row_count': len(all_rows),
        'rows': all_rows,
    }

    write_json(JOURNAL_PATH, journal_payload)

    learning_state = build_learning_state(all_rows, new_records, source_path, run_generated_at)
    write_json(LEARNING_STATE_PATH, learning_state)
    write_json(LEARNING_DASHBOARD_PATH, learning_state)

    health = {
        'schema_version': 'signal_journal_health_v1',
        'generated_at': now_utc_iso(),
        'status': 'PASS',
        'source_path': source_path,
        'input_rows': len(rows),
        'new_records': len(new_records),
        'total_journal_rows': len(all_rows),
        'paper_only': True,
        'order_submission': False,
        'notes': [
            'Package 4 saves signal history for future learning.',
            'It records skipped and trade-eligible signals.',
            'It does not submit orders.',
            'Outcome labeling is intentionally deferred to a later package.',
        ],
    }
    write_json(HEALTH_PATH, health)

    return {
        'status': 'PASS',
        'source_path': source_path,
        'input_rows': len(rows),
        'new_records': len(new_records),
        'total_journal_rows': len(all_rows),
        'journal_path': str(JOURNAL_PATH),
        'learning_dashboard_path': str(LEARNING_DASHBOARD_PATH),
        'health_path': str(HEALTH_PATH),
    }


def build_learning_state(all_rows: List[Dict[str, Any]], new_records: List[Dict[str, Any]], source_path: Optional[str], run_generated_at: str) -> Dict[str, Any]:
    recent = [row for row in all_rows if isinstance(row, dict)][-250:]

    by_status: Dict[str, int] = {}
    by_bucket: Dict[str, int] = {}
    by_reason: Dict[str, int] = {}

    for row in recent:
        status = str(row.get('status') or 'UNKNOWN')
        bucket = str(row.get('score_bucket') or 'UNKNOWN')
        by_status[status] = by_status.get(status, 0) + 1
        by_bucket[bucket] = by_bucket.get(bucket, 0) + 1

        reasons = row.get('no_trade_reasons') if isinstance(row.get('no_trade_reasons'), list) else []
        for reason in reasons[:5]:
            key = str(reason)
            by_reason[key] = by_reason.get(key, 0) + 1

    trade_eligible_count = by_status.get('TRADE_ELIGIBLE', 0)
    pending_outcomes = sum(
        1 for row in recent
        if isinstance(row.get('future_outcome'), dict)
        and row['future_outcome'].get('status') == 'PENDING'
    )

    # Package 4 is base learning only. It should not change trading thresholds yet.
    adaptive_state = {
        'enabled': False,
        'mode': 'journal_only',
        'min_confidence_adjustment': 0,
        'allow_new_entries': False,
        'reason': 'Package 4 records signals only. Adaptive guard is added later.',
    }

    return {
        'schema_version': 'learning_state_v1',
        'generated_at': now_utc_iso(),
        'source_path': source_path,
        'run_generated_at': run_generated_at,
        'window': {
            'recent_rows_considered': len(recent),
            'total_journal_rows': len(all_rows),
            'new_records_this_run': len(new_records),
        },
        'counts': {
            'by_status': by_status,
            'by_score_bucket': by_bucket,
            'top_no_trade_reasons': dict(sorted(by_reason.items(), key=lambda x: x[1], reverse=True)[:10]),
            'trade_eligible_recent': trade_eligible_count,
            'pending_outcomes': pending_outcomes,
        },
        'learning_readiness': {
            'signal_history_ready': len(all_rows) >= 100,
            'meta_labeling_ready': False,
            'walk_forward_ready': False,
            'reason': 'Need outcome labeling and more history before ML.',
        },
        'adaptive_state': adaptive_state,
        'safety': {
            'paper_only': True,
            'order_submission': False,
            'live_trading': False,
            'this_package_can_trade': False,
        },
    }


def main() -> None:
    print(json.dumps(append_signal_history(), indent=2))


if __name__ == '__main__':
    main()

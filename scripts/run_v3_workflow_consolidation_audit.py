from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKFLOWS = Path(".github/workflows")
DOCS = Path("docs/data/prediction_engine")
STATE = Path("state/prediction_engine")

OUT_DOCS = DOCS / "v3_workflow_consolidation_audit.json"
OUT_HEALTH = DOCS / "v3_workflow_consolidation_audit_health.json"
OUT_STATE = STATE / "v3_workflow_consolidation_audit.json"


MANUAL_ONLY_HINTS = {
    "sec",
    "adaptive",
    "advanced",
    "finra",
    "free scanner",
    "normalizer",
    "market rule",
    "outcome",
    "paper execution",
    "signal journal",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(errors="replace")


def extract_name(text: str, fallback: str) -> str:
    m = re.search(r"(?m)^\s*name:\s*(.+?)\s*$", text)
    return m.group(1).strip().strip('"').strip("'") if m else fallback


def has_schedule(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*schedule\s*:", text) or re.search(r"(?m)^\s*-\s*cron\s*:", text))


def has_workflow_dispatch(text: str) -> bool:
    return "workflow_dispatch" in text


def has_write_permissions(text: str) -> bool:
    return "contents: write" in text or "contents:write" in text.replace(" ", "")


def has_git_commit_push(text: str) -> bool:
    return bool(re.search(r"\bgit\s+commit\b", text) or re.search(r"\bgit\s+push\b", text))


def extract_crons(text: str) -> list[str]:
    return re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", text)


def extract_scripts(text: str) -> list[str]:
    return re.findall(r"python(?:3)?\s+([A-Za-z0-9_./-]*scripts/[A-Za-z0-9_./-]+\.py)", text)


def recommendation_for(name: str, filename: str, scheduled: bool, writes: bool, scripts: list[str]) -> str:
    key = f"{name} {filename}".lower()

    if "pages" in key or "deployment" in key:
        return "KEEP_SYSTEM"

    if any(x in key for x in ["master paid", "master_paid", "runtime", "final repo", "final_repo"]):
        return "KEEP_SCHEDULED"

    if any(h in key for h in MANUAL_ONLY_HINTS):
        return "MAKE_MANUAL_ONLY" if scheduled else "KEEP_MANUAL_ONLY"

    if scheduled and writes:
        return "REVIEW_HIGH_RISK_SCHEDULED_WRITER"

    if scheduled and len(scripts) <= 1:
        return "REVIEW_MAYBE_DUPLICATE"

    return "KEEP_REVIEW"


def main() -> None:
    generated_at = now_iso()
    blockers: list[str] = []
    warnings: list[str] = []

    if not WORKFLOWS.exists():
        blockers.append("missing_github_workflows_folder")
        workflow_files = []
    else:
        workflow_files = sorted([p for p in WORKFLOWS.iterdir() if p.suffix.lower() in {".yml", ".yaml"}])

    workflows = []
    script_usage: dict[str, list[str]] = defaultdict(list)
    scheduled_writers = []
    scheduled_count = 0
    writer_count = 0

    for path in workflow_files:
        text = read_text(path)
        name = extract_name(text, path.stem)
        scheduled = has_schedule(text)
        dispatch = has_workflow_dispatch(text)
        write_perm = has_write_permissions(text)
        git_write = has_git_commit_push(text)
        writes = write_perm or git_write
        crons = extract_crons(text)
        scripts = extract_scripts(text)
        recommendation = recommendation_for(name, path.name, scheduled, writes, scripts)

        if scheduled:
            scheduled_count += 1
        if writes:
            writer_count += 1
        if scheduled and writes:
            scheduled_writers.append(path.name)

        for script in scripts:
            script_usage[script].append(path.name)

        workflows.append({
            "file": str(path),
            "filename": path.name,
            "name": name,
            "scheduled": scheduled,
            "workflow_dispatch": dispatch,
            "writes": writes,
            "contents_write": write_perm,
            "git_commit_push": git_write,
            "crons": crons,
            "scripts": scripts,
            "script_count": len(scripts),
            "recommendation": recommendation,
        })

    duplicate_scripts = {script: files for script, files in sorted(script_usage.items()) if len(files) > 1}

    if scheduled_count > 4:
        warnings.append("too_many_scheduled_workflows")
    if len(scheduled_writers) > 2:
        warnings.append("multiple_scheduled_workflows_can_write")
    if duplicate_scripts:
        warnings.append("duplicate_script_usage_across_workflows")

    suggested_keep_scheduled = [
        w for w in workflows if w["recommendation"] in {"KEEP_SCHEDULED", "KEEP_SYSTEM"}
    ]

    suggested_manual_only = [
        w for w in workflows
        if w["recommendation"] in {
            "MAKE_MANUAL_ONLY",
            "KEEP_MANUAL_ONLY",
            "REVIEW_HIGH_RISK_SCHEDULED_WRITER",
            "REVIEW_MAYBE_DUPLICATE",
        }
    ]

    status = "PASS" if not blockers else "FAIL"
    if status == "PASS" and warnings:
        status = "WARN"

    health = {
        "schema_version": "v3_workflow_consolidation_audit_health_v1",
        "generated_at": generated_at,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "workflow_count": len(workflows),
        "scheduled_workflows": scheduled_count,
        "writer_workflows": writer_count,
        "scheduled_writer_workflows": len(scheduled_writers),
        "duplicate_script_count": len(duplicate_scripts),
        "suggested_keep_scheduled_count": len(suggested_keep_scheduled),
        "suggested_manual_only_count": len(suggested_manual_only),
        "order_submission": False,
        "live_trading": False,
    }

    out = {
        "schema_version": "v3_workflow_consolidation_audit_v1",
        "generated_at": generated_at,
        "health": health,
        "workflows": workflows,
        "scheduled_writers": scheduled_writers,
        "duplicate_scripts": duplicate_scripts,
        "suggested_keep_scheduled": suggested_keep_scheduled,
        "suggested_manual_only": suggested_manual_only,
        "recommendation": {
            "main_read": "Consolidate scheduled jobs into master pipeline plus runtime validation/final audit/pages. Make package-level scanners manual-only or called from master pipeline.",
            "do_not_delete_yet": True,
            "next_step": "Review recommendations, then patch workflow schedules safely.",
        },
        "safety": {
            "audit_only": True,
            "order_submission": False,
            "live_trading": False,
        },
    }

    write_json(OUT_DOCS, out)
    write_json(OUT_HEALTH, health)
    write_json(OUT_STATE, out)

    print(json.dumps(health, indent=2))

    if status == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

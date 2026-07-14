#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate KOSIS_API_KEY-only collection and restore the pre-run snapshot on failure.

Rollback protects the published official records only. It never changes the promoted
mapping, API key, repository Secrets, or generated runtime URLs.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY = DATA / "config" / "kosis_single_key_runtime_policy.json"
OPERATIONAL = DATA / "config" / "kosis_table_mapping_operational.json"
COLLECTION = DATA / "admin" / "real_official_source_connections.json"
RECORDS = DATA / "official" / "manual" / "real_source_metrics.json"
BACKUP = ROOT / ".runtime" / "kosis" / "real_source_metrics.before.json"
ADMIN_OUT = DATA / "admin" / "kosis_single_key_runtime_validation.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_single_key_runtime_validation.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def target_metrics(mapping: dict) -> set[str]:
    out: set[str] = set()
    for table in mapping.get("tables", []) or []:
        if not isinstance(table, dict) or not table.get("selected"):
            continue
        for metric in table.get("metric_mappings", []) or []:
            if isinstance(metric, dict) and metric.get("enabled", True) and metric.get("metric_id"):
                out.add(str(metric["metric_id"]))
    return out


def consecutive(history: list[dict], passed: bool) -> int:
    count = 0
    for row in history:
        if bool(row.get("passed")) is passed:
            count += 1
        else:
            break
    return count


def main() -> int:
    checked_at = now_iso()
    policy = read_json(POLICY, {})
    thresholds = policy.get("thresholds") or {}
    operational = read_json(OPERATIONAL, {"tables": []})
    collection = read_json(COLLECTION, {"sources": [], "summary": {}})
    records_doc = read_json(RECORDS, {"records": []})
    previous = read_json(ADMIN_OUT, {"history": [], "summary": {}})

    api_key_present = bool(os.environ.get("KOSIS_API_KEY", "").strip())
    legacy_names = list(policy.get("legacy_secret_names") or [])
    legacy_presence = {name: bool(os.environ.get(name, "").strip()) for name in legacy_names}
    legacy_absent = not any(legacy_presence.values())
    promoted = str(operational.get("promotion_status") or "") == "promoted" and bool(operational.get("tables"))
    single_key_mode = promoted and api_key_present and legacy_absent

    sources = [x for x in collection.get("sources", []) or [] if str(x.get("source_id") or "").startswith("KOSIS_")]
    successes = sum(1 for x in sources if x.get("status") == "success" and x.get("endpoint_mode") == "operational_runtime")
    failures = sum(1 for x in sources if x.get("status") in {"failed", "empty", "mapping_required", "credential_required"})
    records = [x for x in records_doc.get("records", []) or [] if str(x.get("source_id") or "").startswith("KOSIS_")]
    exact = sum(1 for x in records if x.get("mapping_mode") == "operational_code_match")
    match_rate = round(exact / len(records) * 100, 1) if records else 0.0
    targets = target_metrics(operational)
    covered = {str(x.get("metric_id")) for x in records if x.get("metric_id")} & targets
    coverage = round(len(covered) / len(targets) * 100, 1) if targets else 0.0

    checks = {
        "operational_mapping_promoted": promoted,
        "kosis_api_key_present": api_key_present,
        "legacy_url_secrets_absent": legacy_absent,
        "minimum_successful_sources": successes >= int(thresholds.get("minimum_successful_kosis_sources", 2)),
        "no_failed_or_empty_sources": failures <= int(thresholds.get("maximum_failed_kosis_sources", 0)),
        "minimum_records": len(records) >= int(thresholds.get("minimum_collected_records", 2)),
        "operational_match_rate": match_rate >= float(thresholds.get("minimum_operational_code_match_rate_percent", 95)),
        "metric_coverage": coverage >= float(thresholds.get("minimum_metric_coverage_percent", 80)),
    }
    run_passed = single_key_mode and all(checks.values())
    rollback_applied = False
    rollback_reason: list[str] = []
    if single_key_mode and not run_passed:
        rollback_reason = [name for name, ok in checks.items() if not ok]
        if BACKUP.exists() and bool((policy.get("rollback") or {}).get("restore_previous_official_records", True)):
            RECORDS.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(BACKUP, RECORDS)
            rollback_applied = True

    run = {
        "checked_at": checked_at,
        "passed": run_passed,
        "single_key_mode": single_key_mode,
        "api_key_present": api_key_present,
        "legacy_secrets_absent": legacy_absent,
        "successful_kosis_source_count": successes,
        "failed_or_empty_kosis_source_count": failures,
        "record_count": len(records),
        "operational_code_match_rate_percent": match_rate,
        "metric_coverage_percent": coverage,
        "covered_metrics": sorted(covered),
        "missing_metrics": sorted(targets - covered),
        "checks": checks,
        "rollback_applied": rollback_applied,
        "rollback_reason": rollback_reason,
    }
    history = [run] + [x for x in previous.get("history", []) or [] if isinstance(x, dict)]
    history = history[: int(thresholds.get("history_limit", 30))]
    success_streak = consecutive(history, True)
    failure_streak = consecutive(history, False)
    previous_state = str((previous.get("summary") or {}).get("rollback_state") or "inactive")
    recovery_required = int(thresholds.get("recovery_after_consecutive_successful_probes", 2))
    ready_required = int(thresholds.get("minimum_consecutive_successful_runs", 3))

    if not promoted:
        status, rollback_state = "operational_setup_required", "inactive"
    elif not api_key_present:
        status, rollback_state = "credential_required", "safe_hold"
    elif not legacy_absent:
        status, rollback_state = "legacy_secret_removal_required", "inactive"
    elif rollback_applied:
        status, rollback_state = "rolled_back", "safe_hold"
    elif previous_state in {"safe_hold", "recovering"} and success_streak < recovery_required:
        status, rollback_state = "recovery_probing", "recovering"
    elif run_passed and success_streak >= ready_required:
        status, rollback_state = "single_key_ready", "inactive"
    elif run_passed:
        status, rollback_state = "validating", "inactive"
    else:
        status, rollback_state = "validation_failed", "safe_hold"

    summary = {
        "status": status,
        "rollback_state": rollback_state,
        "single_key_mode": single_key_mode,
        "run_passed": run_passed,
        "rollback_applied": rollback_applied,
        "consecutive_successful_runs": success_streak,
        "consecutive_failed_runs": failure_streak,
        "required_successful_runs": ready_required,
        "recovery_successful_probes_required": recovery_required,
        "operational_mapping_preserved": True,
        "secret_values_exposed": False,
    }
    payload = {
        "updated_at": checked_at,
        "policy": policy.get("policy", "phase9_kosis_single_key_runtime_v1"),
        "summary": summary,
        "current_run": run,
        "history": history,
        "legacy_secret_presence": {name: present for name, present in legacy_presence.items()},
        "security": policy.get("security") or {},
        "next_action": (
            "자동 롤백된 이전 공식데이터를 유지한 채 다음 Update market data 실행에서 KOSIS_API_KEY 단독 경로를 다시 검증하세요."
            if rollback_applied else
            "연속 성공 기준을 충족할 때까지 Update market data 실행 결과를 확인하세요."
        ),
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

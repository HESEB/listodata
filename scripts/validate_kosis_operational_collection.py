#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate promoted KOSIS runtime collection before legacy Secret retirement.

The validator records a bounded run history, checks operational-code matching and
metric coverage, and recommends a phaseout stage. It never exposes or deletes
Secrets and never marks legacy URLs disabled without explicit administrator approval.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY = DATA / "config" / "kosis_legacy_secret_phaseout_policy.json"
APPROVAL = DATA / "admin" / "kosis_legacy_secret_phaseout_approval.json"
RUNTIME = DATA / "admin" / "kosis_runtime_mapping_status.json"
COLLECTION = DATA / "admin" / "real_official_source_connections.json"
RECORDS = DATA / "official" / "manual" / "real_source_metrics.json"
OPERATIONAL = DATA / "config" / "kosis_table_mapping_operational.json"
ADMIN_OUT = DATA / "admin" / "kosis_operational_collection_validation.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_operational_collection_validation.json"


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
    result: set[str] = set()
    for table in mapping.get("tables", []) or []:
        if not isinstance(table, dict) or not table.get("selected"):
            continue
        for metric in table.get("metric_mappings", []) or []:
            if isinstance(metric, dict) and metric.get("enabled", True) and metric.get("metric_id"):
                result.add(str(metric["metric_id"]))
    return result


def main() -> int:
    checked_at = now_iso()
    policy = read_json(POLICY, {})
    approval = read_json(APPROVAL, {})
    runtime = read_json(RUNTIME, {"summary": {}, "sources": []})
    collection = read_json(COLLECTION, {"summary": {}, "sources": []})
    records_doc = read_json(RECORDS, {"records": []})
    operational = read_json(OPERATIONAL, {"tables": []})
    previous = read_json(ADMIN_OUT, {"history": []})
    thresholds = policy.get("thresholds") or {}

    kosis_sources = [x for x in collection.get("sources", []) or [] if str(x.get("source_id") or "").startswith("KOSIS_")]
    successful_sources = sum(1 for x in kosis_sources if x.get("status") == "success")
    failed_sources = sum(1 for x in kosis_sources if x.get("status") == "failed")
    operational_sources = sum(1 for x in kosis_sources if x.get("endpoint_mode") == "operational_runtime")

    records = [x for x in records_doc.get("records", []) or [] if str(x.get("source_id") or "").startswith("KOSIS_")]
    operational_matches = sum(1 for x in records if x.get("mapping_mode") == "operational_code_match")
    match_rate = round((operational_matches / len(records) * 100), 1) if records else 0.0
    targets = target_metrics(operational)
    collected_metrics = {str(x.get("metric_id")) for x in records if x.get("metric_id")}
    covered = targets & collected_metrics
    coverage = round((len(covered) / len(targets) * 100), 1) if targets else 0.0

    checks = {
        "operational_mapping_promoted": str(operational.get("promotion_status") or "") == "promoted",
        "operational_runtime_active": (runtime.get("summary") or {}).get("mapping_source") == "operational",
        "minimum_successful_sources": successful_sources >= int(thresholds.get("minimum_successful_kosis_sources_per_run", 2)),
        "no_failed_sources": failed_sources <= int(thresholds.get("maximum_failed_kosis_sources_per_run", 0)),
        "minimum_records": len(records) >= int(thresholds.get("minimum_collected_records_per_run", 2)),
        "operational_match_rate": match_rate >= float(thresholds.get("minimum_operational_code_match_rate_percent", 95)),
        "metric_coverage": coverage >= float(thresholds.get("minimum_metric_coverage_percent", 80)),
    }
    run_passed = all(checks.values())
    run = {
        "checked_at": checked_at,
        "passed": run_passed,
        "successful_kosis_source_count": successful_sources,
        "failed_kosis_source_count": failed_sources,
        "operational_runtime_source_count": operational_sources,
        "record_count": len(records),
        "operational_code_match_count": operational_matches,
        "operational_code_match_rate_percent": match_rate,
        "target_metric_count": len(targets),
        "covered_metric_count": len(covered),
        "metric_coverage_percent": coverage,
        "covered_metrics": sorted(covered),
        "missing_metrics": sorted(targets - collected_metrics),
        "checks": checks,
    }

    history = [run] + [x for x in previous.get("history", []) or [] if isinstance(x, dict)]
    history = history[: int(thresholds.get("history_limit", 30))]
    consecutive = 0
    for row in history:
        if row.get("passed"):
            consecutive += 1
        else:
            break

    required_runs = int(thresholds.get("minimum_consecutive_successful_runs", 3))
    candidate = consecutive >= required_runs
    approval_valid = (
        str(approval.get("decision") or "") == "approve"
        and str(approval.get("approved_stage") or "") == "legacy_disabled"
        and bool(approval.get("reviewer"))
        and str(approval.get("expected_validation_policy") or "") == "phase9_kosis_operational_collection_validation_v1"
    )

    if approval_valid and candidate:
        stage = "legacy_disabled"
        status = "legacy_disable_approved"
    elif candidate:
        stage = "deprecation_candidate"
        status = "approval_required"
    elif checks["operational_mapping_promoted"] and checks["operational_runtime_active"]:
        stage = "shadow_validation"
        status = "collecting_evidence"
    else:
        stage = "legacy_active"
        status = "operational_setup_required"

    summary = {
        "status": status,
        "effective_stage": stage,
        "run_passed": run_passed,
        "consecutive_successful_runs": consecutive,
        "required_consecutive_successful_runs": required_runs,
        "deprecation_candidate": candidate,
        "admin_approval_valid": approval_valid,
        "legacy_secret_removal_allowed": stage == "legacy_disabled",
        "legacy_secret_values_exposed": False,
    }
    payload = {
        "updated_at": checked_at,
        "policy": "phase9_kosis_operational_collection_validation_v1",
        "summary": summary,
        "current_run": run,
        "history": history,
        "thresholds": thresholds,
        "legacy_secret_names": policy.get("legacy_secret_names") or [],
        "approval": {
            "decision": approval.get("decision"),
            "approved_stage": approval.get("approved_stage"),
            "reviewer_present": bool(approval.get("reviewer")),
            "reviewed_at": approval.get("reviewed_at"),
        },
        "next_action": (
            "Repository Actions Secrets에서 기존 KOSIS 전체 URL Secret 2개를 제거할 수 있습니다. 제거 후 Update market data를 재실행해 KOSIS_API_KEY 경로만 정상인지 확인하세요."
            if stage == "legacy_disabled"
            else "운영 매핑 승격·KOSIS_API_KEY 등록·연속 성공 표본 확보 후 관리자 폐기 승인을 진행하세요."
        ),
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

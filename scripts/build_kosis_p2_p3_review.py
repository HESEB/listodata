#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build staged P2/P3 review queues and track unresolved KOSIS metrics.

This script never approves candidates or changes mappings. It combines target metrics,
quality-scored candidates, existing decisions, and precheck conflicts into a review plan.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
TARGETS = DATA / "config" / "kosis_code_research_targets.json"
QUALITY = DATA / "admin" / "kosis_candidate_quality.json"
APPROVALS = DATA / "admin" / "kosis_detail_approvals.json"
PRECHECK = DATA / "admin" / "kosis_approval_precheck.json"
POLICY = DATA / "config" / "kosis_p2_p3_review_policy.json"
ADMIN_OUT = DATA / "admin" / "kosis_p2_p3_review.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_p2_p3_review.json"


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


def target_rows(doc: dict) -> list[dict]:
    rows: list[dict] = []
    for target in doc.get("targets", []) or []:
        for metric_id in target.get("metrics", []) or []:
            rows.append({
                "metric_id": str(metric_id),
                "research_id": target.get("research_id"),
                "period_expected": target.get("period_expected"),
                "keywords": target.get("keywords") or [],
            })
    return rows


def candidate_key(row: dict) -> str:
    return "|".join(str(row.get(k) or "") for k in ("metric_id", "org_id", "tbl_id", "ITM_ID", "C1_ID"))


def main() -> int:
    generated_at = now_iso()
    targets = target_rows(read_json(TARGETS, {"targets": []}))
    quality = read_json(QUALITY, {"candidates": [], "summary": {}})
    approvals = read_json(APPROVALS, {"approvals": []})
    precheck = read_json(PRECHECK, {"summary": {}, "issues": []})
    policy = read_json(POLICY, {})

    candidates_by_metric: dict[str, list[dict]] = {}
    for row in quality.get("candidates", []) or []:
        if isinstance(row, dict) and row.get("metric_id"):
            candidates_by_metric.setdefault(str(row["metric_id"]), []).append(row)

    approved_by_metric: dict[str, list[dict]] = {}
    decisions_by_key: dict[str, dict] = {}
    for row in approvals.get("approvals", []) or []:
        if not isinstance(row, dict):
            continue
        decisions_by_key[candidate_key(row)] = row
        if row.get("decision") == "approve" and row.get("metric_id"):
            approved_by_metric.setdefault(str(row["metric_id"]), []).append(row)

    conflict_metrics = set()
    for issue in precheck.get("issues", []) or []:
        if isinstance(issue, dict) and issue.get("metric_id") and str(issue.get("severity")) == "error":
            conflict_metrics.add(str(issue["metric_id"]))
    for metric_id, rows in approved_by_metric.items():
        if len(rows) > 1:
            conflict_metrics.add(metric_id)

    tracker: list[dict] = []
    p2_queue: list[dict] = []
    p3_queue: list[dict] = []
    hold_queue: list[dict] = []

    for target in targets:
        metric_id = target["metric_id"]
        rows = sorted(candidates_by_metric.get(metric_id, []), key=lambda x: (-int(x.get("quality_score") or 0), candidate_key(x)))
        approved = approved_by_metric.get(metric_id, [])
        if metric_id in conflict_metrics:
            state = "conflict"
            next_action = "상충 승인 또는 복수 승인 해소"
        elif len(approved) == 1:
            state = "approved"
            next_action = "승인 매핑 생성 결과 확인"
        elif any(x.get("priority") == "P1" for x in rows):
            state = "p1_pending"
            next_action = "P1 일괄 검수 화면에서 우선 처리"
        elif any(x.get("priority") == "P2" for x in rows):
            state = "p2_review"
            next_action = "P2 후보 검수"
        elif any(x.get("priority") == "P3" for x in rows):
            state = "p3_review"
            next_action = "P3 후보 검수"
        elif rows:
            state = "hold_research"
            next_action = "근거 보완 또는 재조사"
        else:
            state = "no_candidate"
            next_action = "통계표·상세코드 재조사"

        row = {
            **target,
            "state": state,
            "candidate_count": len(rows),
            "approved_count": len(approved),
            "best_score": int(rows[0].get("quality_score") or 0) if rows else 0,
            "best_priority": rows[0].get("priority") if rows else None,
            "next_action": next_action,
            "candidates": rows,
        }
        tracker.append(row)
        for candidate in rows:
            decision = decisions_by_key.get(candidate_key(candidate), {}).get("decision")
            queued = {**candidate, "existing_decision": decision, "metric_state": state}
            if candidate.get("priority") == "P2" and state != "approved":
                p2_queue.append(queued)
            elif candidate.get("priority") == "P3" and state != "approved":
                p3_queue.append(queued)
            elif candidate.get("priority") == "HOLD" and state != "approved":
                hold_queue.append(queued)

    state_counts = {state: sum(1 for x in tracker if x["state"] == state) for state in policy.get("metric_states", [])}
    unresolved = [x["metric_id"] for x in tracker if x["state"] != "approved"]
    if not targets:
        status = "target_configuration_required"
    elif not quality.get("candidates"):
        status = "candidate_generation_required"
    elif conflict_metrics:
        status = "conflict_resolution_required"
    elif not unresolved:
        status = "all_metrics_approved"
    elif p2_queue or p3_queue:
        status = "staged_review_required"
    else:
        status = "research_required"

    summary = {
        "status": status,
        "target_metric_count": len(tracker),
        "approved_metric_count": state_counts.get("approved", 0),
        "unresolved_metric_count": len(unresolved),
        "p2_candidate_count": len(p2_queue),
        "p3_candidate_count": len(p3_queue),
        "hold_candidate_count": len(hold_queue),
        "conflict_metric_count": state_counts.get("conflict", 0),
        "no_candidate_metric_count": state_counts.get("no_candidate", 0),
        "auto_approved_count": 0,
        "auto_applied_count": 0,
    }
    payload = {
        "updated_at": generated_at,
        "policy": "phase10_kosis_p2_p3_review_v1",
        "summary": summary,
        "state_counts": state_counts,
        "metric_tracker": tracker,
        "p2_queue": p2_queue,
        "p3_queue": p3_queue,
        "hold_queue": hold_queue,
        "unresolved_metrics": unresolved,
        "next_action": "P2 검수 후 P3를 순서대로 처리하고 후보 없는 지표는 재조사하세요." if unresolved else "모든 목표 지표 승인 완료. 승인 매핑 생성·비교 단계로 진행하세요.",
        "security": {"api_key_exposed": False, "request_url_exposed": False},
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

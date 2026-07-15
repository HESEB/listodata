#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate KOSIS detail approval JSON before approved mapping generation.

The validator reports schema errors, duplicate candidate keys, conflicting decisions,
multiple approvals for one metric, and stale approvals that no longer match current
official detail-research evidence. It never edits approvals or mapping files.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY = DATA / "config" / "kosis_approval_precheck_policy.json"
APPROVALS = DATA / "admin" / "kosis_detail_approvals.json"
DETAIL = DATA / "admin" / "kosis_detail_research.json"
ADMIN_OUT = DATA / "admin" / "kosis_approval_precheck.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_approval_precheck.json"


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


def text(value: Any) -> str:
    return str(value or "").strip()


def candidate_key(row: dict) -> str:
    return "|".join(text(row.get(field)) for field in ("metric_id", "org_id", "tbl_id", "ITM_ID", "C1_ID"))


def flatten_detail(doc: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for target in doc.get("targets", []) or []:
        research_id = text(target.get("research_id"))
        for table in target.get("tables", []) or []:
            for metric in table.get("metrics", []) or []:
                metric_id = text(metric.get("metric_id"))
                for candidate in metric.get("candidates", []) or []:
                    if not isinstance(candidate, dict):
                        continue
                    row = {
                        "metric_id": metric_id,
                        "research_id": research_id,
                        "org_id": text(table.get("org_id") or candidate.get("org_id")),
                        "tbl_id": text(table.get("tbl_id") or candidate.get("tbl_id")),
                        "ITM_ID": text(candidate.get("ITM_ID")),
                        "C1_ID": text(candidate.get("C1_ID")),
                        "evidence_status": text(candidate.get("evidence_status")),
                        "official_response_checked_at": table.get("official_response_checked_at") or candidate.get("official_response_checked_at"),
                    }
                    result[candidate_key(row)] = row
    return result


def issue(code: str, severity: str, message: str, index: int | None = None, key: str | None = None) -> dict:
    payload = {"code": code, "severity": severity, "message": message}
    if index is not None:
        payload["index"] = index
    if key:
        payload["candidate_key"] = key
    return payload


def main() -> int:
    checked_at = now_iso()
    policy = read_json(POLICY, {})
    approvals_doc = read_json(APPROVALS, {})
    detail_doc = read_json(DETAIL, {})
    rows = approvals_doc.get("approvals") if isinstance(approvals_doc, dict) else None
    current_candidates = flatten_detail(detail_doc)
    problems: list[dict] = []
    warnings: list[dict] = []

    if not isinstance(approvals_doc, dict):
        problems.append(issue("root_not_object", "error", "승인 JSON 최상위는 객체여야 합니다."))
        rows = []
    if text(approvals_doc.get("policy")) != text(policy.get("source_approval_policy")):
        problems.append(issue("policy_mismatch", "error", "승인 JSON policy가 허용 정책과 일치하지 않습니다."))
    if not isinstance(rows, list):
        problems.append(issue("approvals_not_array", "error", "approvals는 배열이어야 합니다."))
        rows = []

    allowed = set(policy.get("allowed_decisions") or [])
    required = list(policy.get("required_approval_fields") or [])
    approve_required = list(policy.get("approve_required_fields") or [])
    seen: dict[str, list[tuple[int, str]]] = defaultdict(list)
    approved_by_metric: dict[str, list[str]] = defaultdict(list)
    valid_count = 0

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(issue("row_not_object", "error", "승인 항목은 객체여야 합니다.", index=index))
            continue
        key = candidate_key(row)
        decision = text(row.get("decision"))
        missing = [field for field in required if not text(row.get(field))]
        if missing:
            problems.append(issue("required_field_missing", "error", "필수값 누락: " + ", ".join(missing), index=index, key=key))
        if decision not in allowed:
            problems.append(issue("invalid_decision", "error", f"허용되지 않은 decision: {decision or '빈값'}", index=index, key=key))
        if decision == "approve":
            missing_approve = [field for field in approve_required if not text(row.get(field))]
            if missing_approve:
                problems.append(issue("approve_field_missing", "error", "승인 필수값 누락: " + ", ".join(missing_approve), index=index, key=key))
            approved_by_metric[text(row.get("metric_id"))].append(key)
            evidence = current_candidates.get(key)
            if evidence is None:
                problems.append(issue("current_candidate_not_found", "error", "현재 공식 상세 조사에서 동일 후보를 찾지 못했습니다.", index=index, key=key))
            else:
                if text(evidence.get("research_id")) != text(row.get("research_id")):
                    problems.append(issue("research_id_conflict", "error", "현재 공식 후보의 research_id와 다릅니다.", index=index, key=key))
                if text(evidence.get("evidence_status")) != "complete":
                    problems.append(issue("evidence_incomplete", "error", "승인 후보의 현재 공식 근거가 complete가 아닙니다.", index=index, key=key))
                if text(evidence.get("official_response_checked_at")) != text(row.get("official_response_checked_at")):
                    warnings.append(issue("evidence_timestamp_changed", "warning", "공식 응답 확인시각이 변경되었습니다. 최신 근거 재확인이 필요합니다.", index=index, key=key))
        seen[key].append((index, decision))
        if not missing and decision in allowed:
            valid_count += 1

    for key, values in seen.items():
        if len(values) > 1:
            decisions = sorted({decision for _, decision in values})
            problems.append(issue("duplicate_candidate_key", "error", f"동일 후보가 {len(values)}회 중복되었습니다: {', '.join(decisions)}", key=key))
            if len(decisions) > 1:
                problems.append(issue("conflicting_decisions", "error", "동일 후보에 상충하는 결정이 존재합니다.", key=key))

    for metric_id, keys in approved_by_metric.items():
        unique_keys = sorted(set(keys))
        if metric_id and len(unique_keys) > 1:
            problems.append(issue("multiple_approvals_per_metric", "error", f"{metric_id} 지표에 승인 후보가 {len(unique_keys)}건입니다."))

    error_count = sum(1 for x in problems if x.get("severity") == "error")
    warning_count = len(warnings)
    if error_count:
        status = "validation_failed"
    elif not rows:
        status = "approval_input_required"
    elif warning_count:
        status = "review_required"
    else:
        status = "ready_for_mapping_generation"

    summary = {
        "status": status,
        "approval_count": len(rows),
        "valid_row_count": valid_count,
        "approved_count": sum(1 for x in rows if isinstance(x, dict) and text(x.get("decision")) == "approve"),
        "hold_count": sum(1 for x in rows if isinstance(x, dict) and text(x.get("decision")) == "hold"),
        "reject_count": sum(1 for x in rows if isinstance(x, dict) and text(x.get("decision")) == "reject"),
        "duplicate_key_count": sum(1 for x in problems if x.get("code") == "duplicate_candidate_key"),
        "conflict_count": sum(1 for x in problems if x.get("code") in {"conflicting_decisions", "multiple_approvals_per_metric", "research_id_conflict"}),
        "error_count": error_count,
        "warning_count": warning_count,
        "mapping_generation_allowed": status == "ready_for_mapping_generation",
        "source_files_modified": False,
    }
    payload = {
        "updated_at": checked_at,
        "policy": "phase10_kosis_approval_precheck_v1",
        "summary": summary,
        "errors": problems,
        "warnings": warnings,
        "candidate_key_fields": policy.get("candidate_key_fields") or [],
        "source": {
            "approval_path": str(APPROVALS.relative_to(ROOT)),
            "detail_research_path": str(DETAIL.relative_to(ROOT)),
            "detail_research_status": (detail_doc.get("summary") or {}).get("status"),
            "current_candidate_count": len(current_candidates),
        },
        "next_action": (
            "오류 항목을 수정한 뒤 승인 JSON 사전점검을 다시 실행하세요."
            if error_count else
            "승인 JSON을 생성·반영하세요."
            if not rows else
            "경고 후보의 최신 공식 근거를 다시 확인하세요."
            if warning_count else
            "승인 매핑 생성 단계로 진행할 수 있습니다."
        ),
        "security": {"api_key_exposed": False, "request_url_exposed": False},
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

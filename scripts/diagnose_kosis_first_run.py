#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose the first KOSIS_API_KEY workflow run without exposing credentials."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY = DATA / "config" / "kosis_first_run_diagnostic_policy.json"
PREFLIGHT = DATA / "admin" / "kosis_preflight_status.json"
CATALOG = DATA / "admin" / "kosis_catalog_research.json"
DETAIL = DATA / "admin" / "kosis_detail_research.json"
RESEARCH = DATA / "admin" / "kosis_code_research.json"
ADMIN_OUT = DATA / "admin" / "kosis_first_run_diagnostic.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_first_run_diagnostic.json"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def flatten_errors(*docs: dict) -> list[str]:
    values: list[str] = []
    for doc in docs:
        for row in doc.get("errors", []) or []:
            if isinstance(row, dict):
                values.append(" ".join(str(v) for v in row.values() if v not in (None, "")))
            else:
                values.append(str(row))
    return values


def classify_error(errors: list[str], classes: dict[str, list[str]]) -> str | None:
    text = " ".join(errors).lower()
    for name, tokens in classes.items():
        if any(str(token).lower() in text for token in tokens):
            return name
    return "unknown_api_error" if errors else None


def main() -> int:
    checked_at = now_iso()
    policy = read_json(POLICY, {})
    preflight = read_json(PREFLIGHT, {"summary": {}})
    catalog = read_json(CATALOG, {"summary": {}})
    detail = read_json(DETAIL, {"summary": {}})
    research = read_json(RESEARCH, {"summary": {}})
    key_present = bool(os.environ.get(str(policy.get("secret_name") or "KOSIS_API_KEY"), "").strip())
    cs, ds, rs = catalog.get("summary") or {}, detail.get("summary") or {}, research.get("summary") or {}
    errors = flatten_errors(catalog, detail)
    error_class = classify_error(errors, policy.get("error_classes") or {})

    catalog_requests = int(cs.get("request_count") or 0)
    catalog_rows = int(cs.get("response_row_count") or 0)
    table_candidates = int(cs.get("candidate_count") or 0)
    detail_requests = int(ds.get("request_count") or 0)
    detail_rows = int(ds.get("detail_row_count") or 0)
    metric_candidates = int(ds.get("metric_candidate_count") or 0)
    approved_candidates = int(ds.get("approved_candidate_count") or 0)

    checks = {
        "secret_detected": key_present,
        "catalog_request_executed": catalog_requests > 0,
        "catalog_response_received": catalog_rows > 0,
        "table_candidate_found": table_candidates > 0,
        "detail_request_executed": detail_requests > 0,
        "detail_response_received": detail_rows > 0,
        "metric_candidate_found": metric_candidates > 0,
        "secret_value_exposed": False,
    }

    if not key_present:
        status = "secret_required"
        next_action = "Repository Actions Secret에 KOSIS_API_KEY를 등록하세요."
    elif catalog_requests == 0 and detail_requests == 0:
        status = "workflow_run_required"
        next_action = "Update market data를 수동 실행하고 완료 후 이 화면을 새로고침하세요."
    elif error_class == "authentication_failed":
        status = "authentication_failed"
        next_action = "KOSIS_API_KEY의 앞뒤 공백·만료·복사 누락을 확인하고 Secret을 다시 저장한 뒤 재실행하세요."
    elif error_class in {"rate_limited", "network_or_endpoint_error", "invalid_response", "unknown_api_error"}:
        status = "network_or_endpoint_error"
        next_action = "Actions 로그에서 KOSIS 목록·상세 조사 단계를 확인하고 잠시 후 재실행하세요. 반복되면 endpoint 설정을 검토하세요."
    elif catalog_rows == 0 or table_candidates == 0:
        status = "catalog_empty"
        next_action = "통계목록 응답은 실행됐지만 후보가 없습니다. 키워드·목록 계층·API 응답 필드 매핑을 검토하세요."
    elif detail_rows == 0 or metric_candidates == 0:
        status = "detail_empty"
        next_action = "통계표 후보는 있으나 상세 항목·분류 후보가 없습니다. 상세 API 응답 구조와 ITM_ID·C1_ID 별칭을 검토하세요."
    elif approved_candidates > 0 or str(rs.get("status") or "") in {"candidate_ready", "table_candidate_found"}:
        status = "candidate_review_required"
        next_action = "KOSIS 상세후보 승인 화면에서 공식 코드와 단위를 검수하세요."
    else:
        status = "first_run_success"
        next_action = "첫 실행 진단이 완료됐습니다. 상세후보 승인 단계로 이동하세요."

    payload = {
        "updated_at": checked_at,
        "policy": "phase10_kosis_first_run_diagnostic_v1",
        "summary": {
            "status": status,
            "secret_configured": key_present,
            "error_class": error_class,
            "catalog_request_count": catalog_requests,
            "catalog_row_count": catalog_rows,
            "table_candidate_count": table_candidates,
            "detail_request_count": detail_requests,
            "detail_row_count": detail_rows,
            "metric_candidate_count": metric_candidates,
            "approved_candidate_count": approved_candidates,
            "phase9_research_status": rs.get("status"),
            "api_key_exposed": False,
        },
        "checks": checks,
        "errors": errors[:50],
        "next_action": next_action,
        "troubleshooting": [
            {"code": "secret_required", "action": "KOSIS_API_KEY 이름과 값 등록 여부 확인"},
            {"code": "workflow_run_required", "action": "Update market data 수동 실행"},
            {"code": "authentication_failed", "action": "키 재발급·공백 제거·Secret 재저장"},
            {"code": "network_or_endpoint_error", "action": "Actions 로그와 endpoint·호출 제한 확인"},
            {"code": "catalog_empty", "action": "목록 API 응답 필드와 검색 키워드 검토"},
            {"code": "detail_empty", "action": "상세 API 응답의 ITM_ID·C1_ID 별칭 검토"},
            {"code": "candidate_review_required", "action": "관리자 상세후보 검수·승인"}
        ],
        "source_status": {
            "preflight": (preflight.get("summary") or {}).get("status"),
            "catalog": cs.get("status"),
            "detail": ds.get("status"),
            "research": rs.get("status"),
        },
        "security": policy.get("security") or {},
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

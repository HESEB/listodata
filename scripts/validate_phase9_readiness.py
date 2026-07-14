#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Phase 9 final validation and operational transition checklist."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ADMIN_OUT = DATA / "admin" / "phase9_readiness.json"
ANALYSIS_OUT = DATA / "analysis" / "phase9_readiness.json"

PATHS = {
    "catalog": DATA / "admin" / "kosis_catalog_research.json",
    "detail": DATA / "admin" / "kosis_detail_research.json",
    "generation": DATA / "admin" / "kosis_mapping_generation.json",
    "promotion": DATA / "admin" / "kosis_mapping_promotion_status.json",
    "runtime": DATA / "admin" / "kosis_runtime_mapping_status.json",
    "collection": DATA / "admin" / "kosis_operational_collection_validation.json",
    "single_key": DATA / "admin" / "kosis_single_key_runtime_validation.json",
    "operational_mapping": DATA / "config" / "kosis_table_mapping_operational.json",
}


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


def summary(name: str) -> dict:
    return (read_json(PATHS[name], {"summary": {}}).get("summary") or {})


def main() -> int:
    checked_at = now_iso()
    catalog = summary("catalog")
    detail = summary("detail")
    generation = summary("generation")
    promotion = summary("promotion")
    runtime = summary("runtime")
    collection = summary("collection")
    single_key = summary("single_key")
    operational = read_json(PATHS["operational_mapping"], {})

    checks = [
        {"id":"phase9_1_3_research","label":"통계목록·상세코드 자동조사","required":True,"passed": bool(catalog.get("secret_configured")) and int(detail.get("metric_candidate_count",0)) > 0,"status": detail.get("status") or catalog.get("status") or "not_run","next_action":"KOSIS_API_KEY 등록 후 Update market data 실행"},
        {"id":"phase9_4_approved_mapping","label":"상세후보 승인·승인 매핑 생성","required":True,"passed": int(generation.get("mapped_metric_count",0)) >= 10 and int(generation.get("unresolved_metric_count",10)) == 0,"status": generation.get("status") or "approval_required","next_action":"10개 지표 상세후보를 검수·승인"},
        {"id":"phase9_5_promotion","label":"운영 매핑 검증·승격","required":True,"passed": str(operational.get("promotion_status")) == "promoted" and int(promotion.get("error_count",1)) == 0,"status": promotion.get("status") or operational.get("promotion_status") or "not_promoted","next_action":"운영 승격 승인 후 Promote KOSIS operational mapping 실행"},
        {"id":"phase9_6_runtime","label":"운영 매핑 런타임 수집 연결","required":True,"passed": runtime.get("mapping_source") == "operational" and int(runtime.get("successful_kosis_source_count",0)) >= 2,"status": runtime.get("status") or "fallback","next_action":"KOSIS_API_KEY로 운영 런타임 수집 성공 확인"},
        {"id":"phase9_7_phaseout","label":"기존 전체 URL Secret 단계적 폐기","required":False,"passed": bool(collection.get("legacy_secret_removal_allowed")),"status": collection.get("effective_stage") or collection.get("status") or "legacy_active","next_action":"연속 성공 3회 후 관리자 폐기 승인"},
        {"id":"phase9_8_single_key","label":"KOSIS_API_KEY 단독 수집·자동 롤백","required":True,"passed": single_key.get("status") == "single_key_ready" and int(single_key.get("consecutive_successful_runs",0)) >= int(single_key.get("required_successful_runs",3)),"status": single_key.get("status") or "operational_setup_required","next_action":"기존 URL Secret 제거 후 단독키 성공 3회 확인"},
        {"id":"rollback_guard","label":"실패 시 이전 공식데이터 복원 보호","required":True,"passed": bool(single_key.get("operational_mapping_preserved", True)) and single_key.get("rollback_state") in {"inactive","monitoring","recovered"},"status": single_key.get("rollback_state") or "unknown","next_action":"자동 롤백 상태와 복구 프로브 확인"},
    ]

    required = [x for x in checks if x["required"]]
    passed_required = sum(1 for x in required if x["passed"])
    if passed_required == len(required):
        status, verdict = "ready", "운영 전환 가능"
    elif passed_required >= 3:
        status, verdict = "limited", "구조 완료 · 운영 검증 진행 중"
    else:
        status, verdict = "setup_required", "사용자 설정·승인·실행 필요"

    payload = {
        "updated_at": checked_at,
        "policy": "phase9_final_readiness_v1",
        "summary": {
            "status": status,
            "verdict": verdict,
            "check_count": len(checks),
            "required_check_count": len(required),
            "passed_required_check_count": passed_required,
            "failed_required_check_count": len(required)-passed_required,
            "operational_mapping_promoted": str(operational.get("promotion_status")) == "promoted",
            "single_key_ready": single_key.get("status") == "single_key_ready",
        },
        "checks": checks,
        "transition_order": [
            "KOSIS_API_KEY 등록",
            "통계표·항목·분류 후보 자동조사",
            "10개 지표 관리자 승인",
            "운영 매핑 승격",
            "운영 수집 연속 성공 검증",
            "기존 전체 URL Secret 폐기 승인",
            "KOSIS_API_KEY 단독 수집 3회 검증",
            "Phase 9 최종 상태 ready 확인",
        ],
        "security": {"secret_values_exposed": False, "operational_mapping_auto_deleted": False},
        "notice": "구조 파일 존재와 실제 운영 성공을 분리 판정합니다. Actions 실행 전에는 setup_required 또는 limited가 정상입니다.",
    }
    write_json(ADMIN_OUT, payload); write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

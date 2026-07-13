#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 7-10 final validation for HESEB DSS 2.0.

The validator distinguishes implementation integrity from live-data readiness:
- PASS: required component exists and is structurally connected.
- LIMITED: implementation exists, but official data is insufficient for decisions.
- FAIL: required file, output contract, or workflow connection is missing.

It never invents market values and does not fail the workflow merely because an
external official-data source has not yet been configured.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
WORKFLOW = ROOT / ".github" / "workflows" / "update-market-data.yml"
ADMIN_OUT = DATA / "admin" / "dss2_final_validation.json"
ANALYSIS_OUT = DATA / "analysis" / "dss2_final_validation.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_file(check_id: str, label: str, path: str, required_keys: list[str] | None = None) -> dict:
    full = ROOT / path
    if not full.exists():
        return {"id": check_id, "label": label, "status": "fail", "message": f"필수 파일 없음: {path}", "path": path}
    if required_keys and full.suffix == ".json":
        doc = read_json(full, {})
        missing = [key for key in required_keys if key not in doc]
        if missing:
            return {"id": check_id, "label": label, "status": "fail", "message": "필수 키 누락: " + ", ".join(missing), "path": path}
    return {"id": check_id, "label": label, "status": "pass", "message": "구조 확인", "path": path}


def workflow_check() -> dict:
    if not WORKFLOW.exists():
        return {"id": "workflow", "label": "자동 업데이트 연결", "status": "fail", "message": "Workflow 파일 없음"}
    text = WORKFLOW.read_text(encoding="utf-8")
    required = [
        "collect_official_metrics.py",
        "validate_official_data_layers.py",
        "build_official_data_quality.py",
        "build_direction_engine_v2.py",
        "build_recommendation_engine.py",
        "build_representative_news.py",
        "build_report_sentences.py",
        "build_data_first_dashboard.py",
        "build_admin2_dashboard.py",
        "validate_dss2_final.py",
    ]
    missing = [x for x in required if x not in text]
    if missing:
        return {"id": "workflow", "label": "자동 업데이트 연결", "status": "fail", "message": "Workflow 단계 누락: " + ", ".join(missing)}
    return {"id": "workflow", "label": "자동 업데이트 연결", "status": "pass", "message": "Phase 7 전체 실행 순서 연결"}


def live_data_check() -> dict:
    collection = read_json(DATA / "admin" / "official_data_collection.json", {})
    quality = read_json(DATA / "admin" / "official_data_quality.json", {})
    summary = collection.get("summary", {}) if isinstance(collection, dict) else {}
    quality_summary = quality.get("summary", {}) if isinstance(quality, dict) else {}
    collected = int(summary.get("valid_record_count") or summary.get("collected_record_count") or summary.get("record_count") or 0)
    active = int(summary.get("active_source_count") or 0)
    ready = int(quality_summary.get("ready_count") or 0)
    if collected <= 0 or active <= 0:
        return {
            "id": "live_official_data",
            "label": "공식 데이터 운영 준비도",
            "status": "limited",
            "message": "공식 데이터 활성 소스 또는 유효 레코드가 없어 시장판단은 유보됨",
            "details": {"active_source_count": active, "valid_record_count": collected, "ready_species_count": ready},
        }
    if ready <= 0:
        return {
            "id": "live_official_data",
            "label": "공식 데이터 운영 준비도",
            "status": "limited",
            "message": "데이터는 수집됐으나 품질·커버리지 기준을 통과한 축종이 없음",
            "details": {"active_source_count": active, "valid_record_count": collected, "ready_species_count": ready},
        }
    return {
        "id": "live_official_data",
        "label": "공식 데이터 운영 준비도",
        "status": "pass",
        "message": f"판단 가능 축종 {ready}개",
        "details": {"active_source_count": active, "valid_record_count": collected, "ready_species_count": ready},
    }


def output_consistency_check() -> dict:
    paths = [
        DATA / "analysis" / "official_data_quality.json",
        DATA / "analysis" / "direction_engine_v2.json",
        DATA / "analysis" / "recommendation_engine.json",
        DATA / "analysis" / "representative_news.json",
        DATA / "analysis" / "report_sentence_engine.json",
        DATA / "display" / "data_first_dashboard.json",
        DATA / "admin" / "admin2_dashboard.json",
    ]
    missing = [str(x.relative_to(ROOT)) for x in paths if not x.exists()]
    if missing:
        return {"id": "output_chain", "label": "분석 출력 체인", "status": "fail", "message": "출력 파일 누락: " + ", ".join(missing)}
    return {"id": "output_chain", "label": "분석 출력 체인", "status": "pass", "message": "Quality → Direction → Recommendation → News → Report → Dashboard 연결"}


def main() -> int:
    checks = [
        check_file("catalog", "공식 데이터 카탈로그", "app/data/design/official_data_catalog.json", ["species"]),
        check_file("schema", "공식 데이터 스키마", "app/data/schema/official_metric.schema.json", ["properties"]),
        check_file("collector", "공식 데이터 수집기", "scripts/collect_official_metrics.py"),
        check_file("quality", "Quality·Coverage·Reliability", "scripts/build_official_data_quality.py"),
        check_file("direction", "Direction Engine 2.0", "scripts/build_direction_engine_v2.py"),
        check_file("recommendation", "Recommendation Engine", "scripts/build_recommendation_engine.py"),
        check_file("representative", "Representative News·Context Filter v2", "scripts/build_representative_news.py"),
        check_file("report", "Report Sentence Engine", "scripts/build_report_sentences.py"),
        check_file("dashboard", "Data First Dashboard", "app/data-first-dashboard.html"),
        check_file("admin2", "Admin 2.0 Dashboard", "app/admin2-dashboard.html"),
        output_consistency_check(),
        workflow_check(),
        live_data_check(),
    ]

    counts = {status: sum(1 for x in checks if x["status"] == status) for status in ["pass", "limited", "fail"]}
    if counts["fail"]:
        overall = "fail"
        label = "구조 보완 필요"
    elif counts["limited"]:
        overall = "limited"
        label = "구조 완료 · 실데이터 연결 필요"
    else:
        overall = "pass"
        label = "DSS 2.0 운영 가능"

    payload = {
        "updated_at": iso_now(),
        "policy": "phase7_dss2_final_validation_v1",
        "summary": {
            "status": overall,
            "label": label,
            "check_count": len(checks),
            "pass_count": counts["pass"],
            "limited_count": counts["limited"],
            "fail_count": counts["fail"],
            "implementation_complete": counts["fail"] == 0,
            "live_decision_ready": counts["fail"] == 0 and counts["limited"] == 0,
        },
        "checks": checks,
        "phase7_completion": {
            "phase_7_0": "설계 기준 고정",
            "phase_7_1": "스키마·저장계층",
            "phase_7_2": "공식 데이터 수집기",
            "phase_7_3": "품질·커버리지·신뢰도",
            "phase_7_4": "Direction Engine 2.0",
            "phase_7_5": "Recommendation Engine",
            "phase_7_6": "대표뉴스·문맥필터",
            "phase_7_7": "보고문장 엔진",
            "phase_7_8": "Data First Dashboard",
            "phase_7_9": "Admin 2.0",
            "phase_7_10": "최종 검증",
        },
        "next_requirements": [
            "KOSIS·공공데이터포털 등 실제 공식 데이터 API/CSV 연결",
            "축종별 핵심지표 Coverage 60% 이상 확보",
            "내부 재고·계약·수요 계획 연결 전까지 추천을 시장 데이터 기준으로 제한",
        ],
        "pages": {
            "dashboard": "app/main.html",
            "data_first_dashboard": "app/data-first-dashboard.html",
            "admin2": "app/admin2-dashboard.html",
            "validation": "app/dss2-final-validation.html",
        },
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

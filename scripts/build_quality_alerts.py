#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build data quality alerts for HESEB Livestock Terminal.

Phase 6-3 converts quality/stability/fallback/review signals into actionable
admin alerts. This creates JSON for a static alert center on GitHub Pages.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ADMIN = DATA / "admin"
ANALYSIS = DATA / "analysis"

INPUTS = {
    "quality": ADMIN / "quality_report.json",
    "classification": ADMIN / "classification_review.json",
    "stability": ADMIN / "update_stability.json",
    "fallback": ADMIN / "fallback_status.json",
    "change_log": ADMIN / "change_log.json",
    "version": DATA / "system" / "version.json",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def alert(alert_id: str, severity: str, category: str, title: str, message: str, action: str, source: str, metric=None) -> dict:
    return {
        "id": alert_id,
        "severity": severity,
        "category": category,
        "title": title,
        "message": message,
        "recommended_action": action,
        "source": source,
        "metric": metric,
    }


def quality_alerts(quality: dict) -> list[dict]:
    out = []
    s = quality.get("summary", {}) if isinstance(quality, dict) else {}
    avg = float(s.get("average_quality") or s.get("avg_quality") or 0)
    raw = int(s.get("raw_count") or 0)
    clean = int(s.get("clean_count") or 0)
    rejected = int(s.get("rejected_count") or 0)
    duplicate = int(s.get("duplicate_count") or 0)
    if raw == 0:
        out.append(alert("QUALITY_RAW_ZERO", "critical", "quality", "Raw 데이터 없음", "자동 수집 원본 데이터가 0건입니다.", "수집 스크립트와 외부 소스 응답 상태 확인", "quality_report", raw))
    if raw and clean == 0:
        out.append(alert("QUALITY_CLEAN_ZERO", "critical", "quality", "Clean 데이터 없음", "수집은 되었으나 정제 통과 데이터가 없습니다.", "필터 사전 과차단 여부와 build_quality_layers 결과 확인", "quality_report", clean))
    if raw and rejected / max(raw, 1) >= 0.7:
        out.append(alert("QUALITY_REJECT_HIGH", "warning", "quality", "Rejected 비율 과다", f"Rejected {rejected}건 / Raw {raw}건으로 제외 비율이 높습니다.", "classification_review와 filter_dictionary 과차단 여부 검토", "quality_report", round(rejected / max(raw, 1) * 100)))
    if avg and avg < 45:
        out.append(alert("QUALITY_AVG_LOW", "warning", "quality", "평균 품질점수 낮음", f"평균 품질점수가 {avg}점입니다.", "출처 레벨, 중복, 축산 맥락 필터를 확인", "quality_report", avg))
    if duplicate and raw and duplicate / max(raw, 1) >= 0.5:
        out.append(alert("QUALITY_DUP_HIGH", "info", "quality", "중복 감지 비율 높음", f"중복 감지 {duplicate}건으로 동일 기사 반복 가능성이 있습니다.", "중복 병합 로직과 원문 URL 기준 확인", "quality_report", duplicate))
    return out


def classification_alerts(classification: dict) -> list[dict]:
    out = []
    items = classification.get("items", []) if isinstance(classification, dict) else []
    summary = classification.get("summary", {}) if isinstance(classification, dict) else {}
    total = int(summary.get("total_review_items") or len(items) or 0)
    high = [x for x in items if str(x.get("priority", "")).lower() in {"high", "critical"} or str(x.get("severity", "")).lower() in {"high", "critical"}]
    force = [x for x in items if x.get("suggested_action") in {"force_include", "change_species", "merge_duplicate"}]
    if total >= 30:
        out.append(alert("CLASS_REVIEW_QUEUE_HIGH", "warning", "classification", "검수 대기 항목 증가", f"자동분류 검수 대기 항목이 {total}건입니다.", "분류검수 페이지에서 우선순위 높은 항목부터 처리", "classification_review", total))
    if high:
        out.append(alert("CLASS_HIGH_PRIORITY", "warning", "classification", "고우선순위 검수 필요", f"고우선순위 검수 항목 {len(high)}건이 있습니다.", "Rejected/축종누락/공식자료 제외 항목 우선 확인", "classification_review", len(high)))
    if force:
        out.append(alert("CLASS_FORCE_ACTIONS", "info", "classification", "수동 보정 후보 존재", f"강제포함·축종변경·중복병합 후보 {len(force)}건이 있습니다.", "패치 JSON 생성 후 사전/로직 반영 검토", "classification_review", len(force)))
    return out


def stability_alerts(stability: dict) -> list[dict]:
    out = []
    s = stability.get("summary", {}) if isinstance(stability, dict) else {}
    score = int(s.get("stability_score") or 0)
    fail = int(s.get("fail_count") or 0)
    missing = int(s.get("missing_count") or 0)
    parse_fail = int(s.get("parse_fail_count") or 0)
    workflow = s.get("workflow_status")
    if fail or missing or parse_fail:
        out.append(alert("STABILITY_FILE_FAILURE", "critical", "stability", "업데이트 산출물 오류", f"실패 {fail}건, 누락 {missing}건, 파싱오류 {parse_fail}건입니다.", "Update Stability 페이지에서 오류 파일 확인 후 Fallback 복원 여부 점검", "update_stability", {"fail": fail, "missing": missing, "parse_fail": parse_fail}))
    if score and score < 80:
        out.append(alert("STABILITY_SCORE_LOW", "warning", "stability", "안정성 점수 낮음", f"업데이트 안정성 점수가 {score}점입니다.", "워크플로 순서와 필수 JSON 키 누락 여부 확인", "update_stability", score))
    if workflow and workflow != "ok":
        out.append(alert("STABILITY_WORKFLOW_WARN", "warning", "workflow", "Workflow 점검 경고", f"Workflow 상태가 {workflow}입니다.", "update-market-data.yml 실행 순서 및 commit file_pattern 확인", "update_stability", workflow))
    return out


def fallback_alerts(fallback: dict) -> list[dict]:
    out = []
    s = fallback.get("summary", {}) if isinstance(fallback, dict) else {}
    coverage = int(s.get("coverage_rate") or 0)
    issues = int(s.get("issue_count") or 0)
    restored = int(s.get("restored_count") or 0)
    grade = s.get("grade")
    if restored:
        out.append(alert("FALLBACK_RESTORED", "warning", "fallback", "Fallback 복원 발생", f"Fallback에서 {restored}개 파일이 복원되었습니다.", "복원 원인 파일과 직전 업데이트 실패 원인 확인", "fallback_status", restored))
    if issues:
        out.append(alert("FALLBACK_ISSUES", "warning", "fallback", "Fallback 보호 이슈", f"Fallback 보호 이슈가 {issues}건 있습니다.", "Fallback Status에서 누락/비정상 스냅샷 파일 확인", "fallback_status", issues))
    if coverage and coverage < 90:
        out.append(alert("FALLBACK_COVERAGE_LOW", "warning", "fallback", "Fallback 커버리지 낮음", f"Fallback 커버리지가 {coverage}%입니다.", "snapshot 단계와 보호 대상 JSON 존재 여부 확인", "fallback_status", coverage))
    if grade == "risk":
        out.append(alert("FALLBACK_RISK", "critical", "fallback", "Fallback 보호 위험", "Fallback 보호 등급이 위험입니다.", "필수 JSON을 정상 생성 후 snapshot 재실행 필요", "fallback_status", grade))
    return out


def build_payload() -> dict:
    quality = read_json(INPUTS["quality"], {})
    classification = read_json(INPUTS["classification"], {})
    stability = read_json(INPUTS["stability"], {})
    fallback = read_json(INPUTS["fallback"], {})
    version = read_json(INPUTS["version"], {})
    alerts = []
    alerts.extend(quality_alerts(quality))
    alerts.extend(classification_alerts(classification))
    alerts.extend(stability_alerts(stability))
    alerts.extend(fallback_alerts(fallback))
    order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda x: (order.get(x["severity"], 9), x["category"], x["id"]))
    counts = {"critical": 0, "warning": 0, "info": 0}
    for a in alerts:
        counts[a["severity"]] = counts.get(a["severity"], 0) + 1
    if counts.get("critical"):
        grade, label = "critical", "긴급"
    elif counts.get("warning"):
        grade, label = "warning", "주의"
    elif counts.get("info"):
        grade, label = "info", "참고"
    else:
        grade, label = "normal", "정상"
    return {
        "updated_at": now_iso(),
        "policy": "phase6_quality_alerts_v1",
        "notice": "품질·안정성·Fallback·분류검수 리포트를 통합해 관리자 경고를 생성합니다.",
        "summary": {
            "total_alerts": len(alerts),
            "critical_count": counts.get("critical", 0),
            "warning_count": counts.get("warning", 0),
            "info_count": counts.get("info", 0),
            "grade": grade,
            "label": label,
            "version": version.get("version") or version.get("build_id") or None,
        },
        "alerts": alerts,
        "sources": {k: "app/data/" + str(v.relative_to(DATA)).replace("\\", "/") for k, v in INPUTS.items()},
    }


def main() -> int:
    payload = build_payload()
    write_json(ADMIN / "quality_alerts.json", payload)
    write_json(ANALYSIS / "quality_alerts.json", payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

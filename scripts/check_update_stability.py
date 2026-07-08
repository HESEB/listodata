#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check data update stability for HESEB Livestock Terminal.

Phase 6-1 validates whether the scheduled data update produced required JSON
files, whether those files are parseable, whether key fields exist, and whether
workflow step order looks safe.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ADMIN = DATA / "admin"
ANALYSIS = DATA / "analysis"
WORKFLOW = ROOT / ".github" / "workflows" / "update-market-data.yml"

REQUIRED_JSONS = [
    (DATA / "market_dashboard.json", "Dashboard 표시 데이터", ["species"]),
    (DATA / "market_metrics.json", "시장 지표 데이터", []),
    (DATA / "events" / "events_news.json", "뉴스 이벤트", []),
    (DATA / "events" / "events_official.json", "공식자료 이벤트", []),
    (DATA / "events" / "event_calendar.json", "이벤트 캘린더", ["items"]),
    (DATA / "raw" / "events_raw.json", "Raw Layer", []),
    (DATA / "clean" / "events_clean.json", "Clean Layer", []),
    (DATA / "clean" / "events_rejected.json", "Rejected Layer", []),
    (ANALYSIS / "evidence_scores.json", "Evidence Score", ["species"]),
    (ANALYSIS / "evidence_chains.json", "Evidence Chain", ["items"]),
    (ANALYSIS / "cross_market_matrix.json", "Cross Market Matrix", ["items"]),
    (ANALYSIS / "conflict_report.json", "Conflict Report", []),
    (ANALYSIS / "history_prediction.json", "History Prediction", []),
    (ANALYSIS / "market_memory.json", "Market Memory", []),
    (ANALYSIS / "case_comparison.json", "Case Comparison", []),
    (ANALYSIS / "classification_review.json", "Classification Review", ["items"]),
    (ANALYSIS / "change_log.json", "Change Log", ["files", "timeline"]),
    (DATA / "history" / "signal_history.json", "Signal History", []),
    (DATA / "display" / "market_dashboard_phase1.json", "Display Layer", []),
    (ADMIN / "quality_report.json", "Admin Quality Report", []),
    (ADMIN / "classification_review.json", "Admin Classification Review", ["items"]),
    (ADMIN / "change_log.json", "Admin Change Log", ["files", "timeline"]),
]

EXPECTED_WORKFLOW_ORDER = [
    "scripts/update_market_data.py",
    "scripts/filter_collected_news.py",
    "scripts/build_quality_layers.py",
    "scripts/build_classification_review.py",
    "scripts/enhance_evidence_chains.py",
    "scripts/detect_conflicts_and_holds.py",
    "scripts/enhance_cross_market_matrix.py",
    "scripts/update_history_prediction.py",
    "scripts/enhance_market_memory.py",
    "scripts/build_case_comparison.py",
    "scripts/postprocess_dashboard_other.py",
    "scripts/build_change_log.py",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(path)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def item_count(data):
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ["items", "species", "groups", "files", "timeline"]:
            if isinstance(data.get(key), list):
                return len(data.get(key))
        summary = data.get("summary")
        if isinstance(summary, dict):
            for key in ["total_review_items", "comparison_count", "watch_file_count", "clean_count", "raw_count"]:
                if key in summary:
                    return summary.get(key)
    return None


def check_json_file(path: Path, label: str, required_keys: list[str]) -> dict:
    row = {
        "path": rel(path),
        "label": label,
        "exists": path.exists(),
        "parse_ok": False,
        "required_keys_ok": False,
        "required_keys": required_keys,
        "missing_keys": [],
        "updated_at": mtime_iso(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "count": None,
        "policy": None,
        "status": "fail",
        "issues": [],
    }
    if not path.exists():
        row["issues"].append("파일 없음")
        return row
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        row["parse_ok"] = True
        row["count"] = item_count(data)
        if isinstance(data, dict):
            row["policy"] = data.get("policy") or data.get("filter_policy") or data.get("dictionary_policy")
            missing = [k for k in required_keys if k not in data]
            row["missing_keys"] = missing
            row["required_keys_ok"] = not missing
            if missing:
                row["issues"].append("필수 키 누락: " + ", ".join(missing))
        else:
            row["required_keys_ok"] = not required_keys
            if required_keys:
                row["missing_keys"] = required_keys
                row["issues"].append("객체 JSON이 아니어서 필수 키 확인 불가")
        if row["size_bytes"] <= 2:
            row["issues"].append("파일 크기 비정상")
        if row["parse_ok"] and row["required_keys_ok"] and not row["issues"]:
            row["status"] = "ok"
        elif row["parse_ok"]:
            row["status"] = "warn"
    except Exception as exc:
        row["issues"].append(f"JSON 파싱 오류: {exc}")
    return row


def check_workflow() -> dict:
    text = read_text(WORKFLOW)
    found = []
    for script in EXPECTED_WORKFLOW_ORDER:
        idx = text.find(script)
        found.append({"script": script, "found": idx >= 0, "position": idx})
    missing = [x["script"] for x in found if not x["found"]]
    order_ok = True
    last = -1
    for x in found:
        if not x["found"]:
            order_ok = False
            continue
        if x["position"] <= last:
            order_ok = False
        last = x["position"]
    file_pattern = "file_pattern:" in text
    stability_in_pattern = "app/data/admin/update_stability.json" in text
    return {
        "path": rel(WORKFLOW),
        "exists": WORKFLOW.exists(),
        "order_ok": order_ok,
        "missing_steps": missing,
        "file_pattern_exists": file_pattern,
        "stability_output_in_commit_pattern": stability_in_pattern,
        "steps": found,
        "status": "ok" if order_ok and not missing and file_pattern and stability_in_pattern else "warn",
    }


def build_summary(files: list[dict], workflow: dict) -> dict:
    total = len(files)
    ok = sum(1 for x in files if x["status"] == "ok")
    warn = sum(1 for x in files if x["status"] == "warn")
    fail = sum(1 for x in files if x["status"] == "fail")
    parse_fail = sum(1 for x in files if x["exists"] and not x["parse_ok"])
    missing = sum(1 for x in files if not x["exists"])
    score = round((ok / total) * 100) if total else 0
    if workflow.get("status") != "ok":
        score = max(0, score - 10)
    if fail:
        score = max(0, score - fail * 5)
    if score >= 90 and workflow.get("status") == "ok":
        grade = "stable"
        label = "안정"
    elif score >= 70:
        grade = "watch"
        label = "주의"
    else:
        grade = "risk"
        label = "위험"
    return {
        "total_files": total,
        "ok_count": ok,
        "warn_count": warn,
        "fail_count": fail,
        "missing_count": missing,
        "parse_fail_count": parse_fail,
        "workflow_status": workflow.get("status"),
        "stability_score": score,
        "stability_grade": grade,
        "stability_label": label,
    }


def main() -> int:
    files = [check_json_file(path, label, keys) for path, label, keys in REQUIRED_JSONS]
    workflow = check_workflow()
    payload = {
        "updated_at": now_iso(),
        "policy": "phase6_update_stability_v1",
        "notice": "자동 업데이트 결과물의 존재, JSON 파싱, 필수 키, 워크플로 순서를 점검한 관리자 리포트입니다.",
        "summary": build_summary(files, workflow),
        "files": files,
        "workflow": workflow,
        "recommendations": build_recommendations(files, workflow),
    }
    write_json(ADMIN / "update_stability.json", payload)
    write_json(ANALYSIS / "update_stability.json", payload)
    return 0


def build_recommendations(files: list[dict], workflow: dict) -> list[str]:
    out = []
    missing = [x["label"] for x in files if not x["exists"]]
    parse_fail = [x["label"] for x in files if x["exists"] and not x["parse_ok"]]
    warn = [x["label"] for x in files if x["status"] == "warn"]
    if missing:
        out.append("누락 파일 생성 스크립트 실행 여부 확인: " + ", ".join(missing[:6]))
    if parse_fail:
        out.append("JSON 파싱 오류 파일 우선 복구: " + ", ".join(parse_fail[:6]))
    if warn:
        out.append("필수 키 또는 데이터 건수 경고 확인: " + ", ".join(warn[:6]))
    if workflow.get("status") != "ok":
        out.append("update-market-data.yml 실행 순서와 commit file_pattern 확인 필요")
    if not out:
        out.append("필수 데이터와 워크플로 점검 결과 정상")
    return out


if __name__ == "__main__":
    raise SystemExit(main())

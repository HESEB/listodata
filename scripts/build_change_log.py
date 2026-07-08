#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Admin change log for HESEB Livestock Terminal.

Phase 3-5 creates a static change log from current data policies, file mtimes,
and lightweight JSON summaries. GitHub Pages cannot persist live admin edits, so
this log records generated data status and known policy versions after each
workflow run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ADMIN = DATA / "admin"
ANALYSIS = DATA / "analysis"
CLEAN = DATA / "clean"
EVENTS = DATA / "events"
SCRIPTS = ROOT / "scripts"
WORKFLOW = ROOT / ".github" / "workflows" / "update-market-data.yml"

WATCH_FILES = [
    DATA / "admin" / "filter_dictionary.json",
    DATA / "admin" / "classification_review.json",
    DATA / "admin" / "quality_report.json",
    DATA / "analysis" / "evidence_scores.json",
    DATA / "analysis" / "evidence_chains.json",
    DATA / "analysis" / "conflict_report.json",
    DATA / "analysis" / "cross_market_matrix.json",
    DATA / "analysis" / "history_prediction.json",
    DATA / "analysis" / "market_memory.json",
    DATA / "analysis" / "case_comparison.json",
    DATA / "clean" / "events_clean.json",
    DATA / "clean" / "events_rejected.json",
    DATA / "events" / "event_calendar.json",
    DATA / "events" / "events_news.json",
    DATA / "events" / "events_official.json",
    SCRIPTS / "filter_collected_news.py",
    SCRIPTS / "build_quality_layers.py",
    SCRIPTS / "build_classification_review.py",
    SCRIPTS / "enhance_evidence_chains.py",
    SCRIPTS / "detect_conflicts_and_holds.py",
    SCRIPTS / "enhance_cross_market_matrix.py",
    SCRIPTS / "update_history_prediction.py",
    SCRIPTS / "enhance_market_memory.py",
    SCRIPTS / "build_case_comparison.py",
    WORKFLOW,
]

CATEGORY = {
    "filter_dictionary.json": "필터 사전",
    "classification_review.json": "자동분류 검수",
    "quality_report.json": "품질 리포트",
    "evidence_scores.json": "점수 엔진",
    "evidence_chains.json": "근거 체인",
    "conflict_report.json": "충돌/유보",
    "cross_market_matrix.json": "축종간 영향",
    "history_prediction.json": "추세/전망",
    "market_memory.json": "시장 메모리",
    "case_comparison.json": "과거 사례 비교",
    "events_clean.json": "정제 데이터",
    "events_rejected.json": "제외 데이터",
    "event_calendar.json": "이벤트 캘린더",
    "events_news.json": "뉴스 원천",
    "events_official.json": "공식자료 원천",
    "filter_collected_news.py": "필터 로직",
    "build_quality_layers.py": "품질/점수 빌더",
    "build_classification_review.py": "분류검수 빌더",
    "enhance_evidence_chains.py": "근거체인 빌더",
    "detect_conflicts_and_holds.py": "충돌감지 빌더",
    "enhance_cross_market_matrix.py": "교차영향 빌더",
    "update_history_prediction.py": "추세 빌더",
    "enhance_market_memory.py": "시장메모리 빌더",
    "build_case_comparison.py": "사례비교 빌더",
    "update-market-data.yml": "자동 업데이트 워크플로",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return 0


def infer_policy(path: Path):
    if path.suffix.lower() != ".json":
        return None
    data = read_json(path, {})
    if isinstance(data, dict):
        return data.get("policy") or data.get("filter_policy") or data.get("dictionary_policy")
    return None


def infer_count(path: Path):
    if path.suffix.lower() != ".json":
        return None
    data = read_json(path, {})
    if isinstance(data, list):
        return len(data)
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("items"), list):
        return len(data.get("items"))
    if isinstance(data.get("species"), list):
        return len(data.get("species"))
    if isinstance(data.get("groups"), list):
        return len(data.get("groups"))
    summary = data.get("summary")
    if isinstance(summary, dict):
        for key in ["total_review_items", "memory_event_count", "comparison_count", "event_count", "clean_count", "rejected_count"]:
            if key in summary:
                return summary.get(key)
    return None


def action_for(path: Path) -> str:
    name = path.name
    if name.endswith(".py"):
        return "로직 확인"
    if name.endswith(".yml"):
        return "자동화 확인"
    if name == "filter_dictionary.json":
        return "사전 변경 검수"
    if name in ["events_rejected.json", "classification_review.json"]:
        return "관리자 검수"
    if name in ["evidence_scores.json", "conflict_report.json", "case_comparison.json"]:
        return "판단 결과 확인"
    return "상태 확인"


def build_file_entries() -> list[dict]:
    entries = []
    for path in WATCH_FILES:
        exists = path.exists()
        entries.append({
            "path": rel(path),
            "name": path.name,
            "category": CATEGORY.get(path.name, "기타"),
            "exists": exists,
            "updated_at": mtime_iso(path),
            "size_bytes": file_size(path),
            "policy": infer_policy(path) if exists else None,
            "count": infer_count(path) if exists else None,
            "admin_action": action_for(path),
        })
    return sorted(entries, key=lambda x: x.get("updated_at") or "", reverse=True)


def policy_snapshot() -> list[dict]:
    out = []
    for path in WATCH_FILES:
        if path.suffix.lower() != ".json" or not path.exists():
            continue
        pol = infer_policy(path)
        if not pol:
            continue
        out.append({"category": CATEGORY.get(path.name, path.name), "path": rel(path), "policy": pol, "updated_at": mtime_iso(path)})
    return out


def admin_timeline(entries: list[dict]) -> list[dict]:
    timeline = []
    for e in entries[:80]:
        if not e.get("exists"):
            continue
        msg = f"{e['category']} 갱신"
        if e.get("policy"):
            msg += f" · {e['policy']}"
        if e.get("count") is not None:
            msg += f" · {e['count']}건"
        timeline.append({
            "time": e.get("updated_at"),
            "category": e.get("category"),
            "message": msg,
            "path": e.get("path"),
            "admin_action": e.get("admin_action"),
        })
    return timeline


def build_payload() -> dict:
    entries = build_file_entries()
    exists_count = sum(1 for e in entries if e.get("exists"))
    missing_count = len(entries) - exists_count
    review = read_json(ADMIN / "classification_review.json", {"summary": {}})
    quality = read_json(ADMIN / "quality_report.json", {"summary": {}})
    return {
        "updated_at": now_iso(),
        "policy": "phase3_change_log_v1",
        "notice": "관리자용 변경 로그입니다. GitHub Pages 정적 구조상 실제 커밋 히스토리 대신 자동생성 데이터·정책버전·파일 상태를 요약합니다.",
        "summary": {
            "watch_file_count": len(entries),
            "exists_count": exists_count,
            "missing_count": missing_count,
            "classification_review_items": review.get("summary", {}).get("total_review_items", 0),
            "quality_clean_count": quality.get("summary", {}).get("clean_count", 0),
            "quality_rejected_count": quality.get("summary", {}).get("rejected_count", 0),
        },
        "timeline": admin_timeline(entries),
        "files": entries,
        "policies": policy_snapshot(),
    }


def main() -> int:
    payload = build_payload()
    write_json(ADMIN / "change_log.json", payload)
    write_json(ANALYSIS / "change_log.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

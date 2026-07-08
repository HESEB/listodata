#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build classification review queue for Admin.

Phase 3-3 creates a static review queue from clean/rejected events so an admin can
inspect auto-classification results and generate JSON patch suggestions.

Because GitHub Pages is static, this script does not persist admin edits. The UI
creates a downloadable/copyable patch proposal for later commit.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CLEAN = DATA / "clean"
ANALYSIS = DATA / "analysis"
ADMIN = DATA / "admin"

SPECIES_LABEL = {"BEEF":"한우","PORK":"돈육","POULTRY":"계육","DUCK":"오리","EGG":"계란","OTHER":"기타"}
DOC_AXIS = {
    "DISEASE": "disease",
    "NOTICE": "policy",
    "MARKET": "supply",
    "INDUSTRY": "news",
    "PRODUCT": "news",
    "GENERAL": "news",
}
AXIS_LABEL = {"price":"가격","supply":"수급/도축","disease":"질병/방역","policy":"정책/고시","news":"뉴스/수요"}


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


def safe_species(item: dict) -> list[str]:
    sp = item.get("species")
    if isinstance(sp, list):
        return sp
    if item.get("_inferred_species"):
        return [item.get("_inferred_species")]
    return []


def review_priority(item: dict, status: str) -> tuple[int, list[str]]:
    reasons = []
    score = 0
    if status == "rejected":
        score += 30
        reasons.append("필터 제외 자료")
    if item.get("quality_score", 100) < 45:
        score += 25
        reasons.append("품질점수 낮음")
    if not safe_species(item):
        score += 20
        reasons.append("축종 미분류")
    if item.get("is_duplicate"):
        score += 12
        reasons.append("중복 후보")
    if item.get("market_direction") in [None, "unknown", ""]:
        score += 10
        reasons.append("방향성 미정")
    if item.get("source_level", 0) >= 5 and status == "rejected":
        score += 18
        reasons.append("공식자료 제외 여부 확인")
    if not reasons:
        reasons.append("표본 검수")
    return min(100, score), reasons


def suggested_action(item: dict, status: str) -> str:
    title = item.get("title", "")
    if status == "rejected":
        if any(k in title for k in ["한우", "돈육", "돼지", "계육", "오리", "계란", "ASF", "조류인플루엔자", "구제역"]):
            return "force_include"
        return "confirm_exclude"
    if item.get("is_duplicate"):
        return "merge_duplicate"
    if not safe_species(item):
        return "change_species"
    if item.get("impact_score", 0) in [0, None]:
        return "edit_impact"
    return "approve"


def normalize_item(item: dict, status: str, idx: int) -> dict:
    priority, reasons = review_priority(item, status)
    species = safe_species(item)
    doc_type = item.get("doc_type") or item.get("evidence_type") or "GENERAL"
    axis = item.get("evidence_axis") or DOC_AXIS.get(doc_type, "news")
    return {
        "review_id": f"{status.upper()}_{idx:04d}",
        "status": status,
        "suggested_action": suggested_action(item, status),
        "priority_score": priority,
        "priority_reasons": reasons,
        "title": item.get("title") or "제목 없음",
        "publisher": item.get("publisher") or item.get("source_title") or item.get("provider") or "",
        "published_at": item.get("published_at") or item.get("date") or "",
        "source_url": item.get("source_url") or item.get("url") or "#",
        "species": species,
        "species_label": [SPECIES_LABEL.get(x, x) for x in species],
        "doc_type": doc_type,
        "evidence_axis": axis,
        "evidence_axis_label": AXIS_LABEL.get(axis, axis),
        "market_direction": item.get("market_direction") or "neutral",
        "impact_score": item.get("impact_score", 0),
        "quality_score": item.get("quality_score", 0),
        "source_level": item.get("source_level", 0),
        "source_level_label": item.get("source_level_label") or "",
        "duplicate_group_id": item.get("duplicate_group_id") or "",
        "is_duplicate": bool(item.get("is_duplicate")),
        "filter_reason": item.get("filter_reason") or item.get("drop_reason") or "",
        "raw_id": item.get("id") or item.get("raw_id") or item.get("event_id") or "",
        "admin_patch_template": {
            "review_id": f"{status.upper()}_{idx:04d}",
            "action": suggested_action(item, status),
            "species": species,
            "market_direction": item.get("market_direction") or "neutral",
            "impact_score": item.get("impact_score", 0),
            "memo": "",
        },
    }


def build_queue() -> dict:
    clean = read_json(CLEAN / "events_clean.json", {"items": []})
    rejected = read_json(CLEAN / "events_rejected.json", {"items": []})
    clean_items = clean.get("items", []) if isinstance(clean, dict) else clean
    rejected_items = rejected.get("items", []) if isinstance(rejected, dict) else rejected

    rows = []
    for idx, item in enumerate(clean_items[-160:], 1):
        rows.append(normalize_item(item, "clean", idx))
    for idx, item in enumerate(rejected_items[-120:], 1):
        rows.append(normalize_item(item, "rejected", idx))

    rows.sort(key=lambda x: (x.get("priority_score", 0), x.get("published_at", "")), reverse=True)
    summary = {
        "total_review_items": len(rows),
        "clean_count": sum(1 for x in rows if x["status"] == "clean"),
        "rejected_count": sum(1 for x in rows if x["status"] == "rejected"),
        "force_include_candidates": sum(1 for x in rows if x["suggested_action"] == "force_include"),
        "change_species_candidates": sum(1 for x in rows if x["suggested_action"] == "change_species"),
        "duplicate_candidates": sum(1 for x in rows if x["suggested_action"] == "merge_duplicate"),
    }
    return {
        "updated_at": now_iso(),
        "policy": "phase3_classification_review_v1",
        "notice": "자동분류 결과를 관리자 검수용 큐로 정리한 정적 데이터입니다. GitHub Pages 특성상 화면 수정값은 패치안으로 복사/다운로드합니다.",
        "summary": summary,
        "items": rows[:180],
        "patch_schema": {
            "action": ["approve", "force_include", "confirm_exclude", "change_species", "edit_impact", "merge_duplicate"],
            "species": ["BEEF", "PORK", "POULTRY", "DUCK", "EGG", "OTHER"],
            "market_direction": ["up", "down", "neutral", "mixed", "hold"],
            "impact_score": "1~5 integer",
        },
    }


def main() -> int:
    payload = build_queue()
    write_json(ADMIN / "classification_review.json", payload)
    write_json(ANALYSIS / "classification_review.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

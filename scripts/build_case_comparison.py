#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build advanced historical case comparison.

Phase 5-3 compares current market signals with historical memory cases.
It is an operational decision-support layer, not a price forecast.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ANALYSIS = DATA / "analysis"
ADMIN = DATA / "admin"

SPECIES_ORDER = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG", "OTHER"]
SPECIES_LABEL = {"BEEF":"한우","PORK":"돈육","POULTRY":"계육","DUCK":"오리","EGG":"계란","OTHER":"기타"}


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


def direction_to_event(direction: str) -> str | None:
    if direction == "up":
        return "signal_jump"
    if direction == "down":
        return "signal_drop"
    return None


def normalize_score_gap(current: float, case_score: float) -> int:
    gap = abs((current or 0) - (case_score or 0))
    return max(0, round(35 - min(35, gap)))


def event_match_score(current: dict, case: dict) -> dict:
    current_dir = current.get("direction")
    target_event = direction_to_event(current_dir)
    score = 0
    reasons = []

    if current.get("id") == case.get("species"):
        score += 25
        reasons.append("축종 일치")
    if target_event and target_event == case.get("event_type"):
        score += 25
        reasons.append("방향성 일치")
    if current.get("conflict", {}).get("severity") == case.get("conflict_severity") and case.get("conflict_severity") not in [None, "none"]:
        score += 10
        reasons.append("충돌 상태 유사")
    score_gap = normalize_score_gap(current.get("signal_score", 0), case.get("to_score", 0))
    score += score_gap
    if score_gap >= 25:
        reasons.append("신호점수 근접")
    nearby = case.get("nearby_calendar_events") or []
    if nearby:
        score += min(15, len(nearby) * 5)
        reasons.append("이벤트 캘린더 연결")

    score = max(0, min(100, score))
    if score >= 75:
        grade = "high"
        label = "높음"
    elif score >= 55:
        grade = "medium"
        label = "중간"
    elif score >= 35:
        grade = "low"
        label = "낮음"
    else:
        grade = "watch"
        label = "관찰"

    return {
        "similarity_score": score,
        "similarity_grade": grade,
        "similarity_label": label,
        "reasons": reasons or ["참고 사례"],
    }


def compare_current_to_cases(scores: dict, memory: dict) -> list[dict]:
    score_items = scores.get("species", [])
    cases = memory.get("items", [])
    out = []
    for cur in score_items:
        sp = cur.get("id")
        relevant = [c for c in cases if c.get("species") == sp]
        ranked = []
        for case in relevant:
            sim = event_match_score(cur, case)
            if sim["similarity_score"] < 25:
                continue
            ranked.append({
                "species": sp,
                "name": SPECIES_LABEL.get(sp, sp),
                "current_status": cur.get("status"),
                "current_direction": cur.get("direction"),
                "current_signal_score": cur.get("signal_score", 0),
                "current_confidence": cur.get("confidence_score", 0),
                "case_date": case.get("date"),
                "case_event_type": case.get("event_type"),
                "case_event_type_label": case.get("event_type_label"),
                "case_change": case.get("change", 0),
                "case_from_score": case.get("from_score", 0),
                "case_to_score": case.get("to_score", 0),
                "case_memo": case.get("memo"),
                "nearby_calendar_events": case.get("nearby_calendar_events", []),
                "purchase_implication": case.get("purchase_implication"),
                **sim,
            })
        out.extend(sorted(ranked, key=lambda x: x.get("similarity_score", 0), reverse=True)[:5])
    return sorted(out, key=lambda x: x.get("similarity_score", 0), reverse=True)


def pattern_summary(memory: dict) -> list[dict]:
    groups = defaultdict(list)
    for case in memory.get("items", []):
        groups[(case.get("species"), case.get("event_type"))].append(case)

    out = []
    for (sp, event_type), cases in groups.items():
        changes = [c.get("change", 0) or 0 for c in cases]
        linked = sum(1 for c in cases if c.get("nearby_calendar_events"))
        avg_change = round(sum(changes) / len(changes), 1) if changes else 0
        max_abs = max(changes, key=lambda x: abs(x)) if changes else 0
        out.append({
            "species": sp,
            "name": SPECIES_LABEL.get(sp, sp),
            "event_type": event_type,
            "event_type_label": cases[0].get("event_type_label") if cases else event_type,
            "case_count": len(cases),
            "avg_change": avg_change,
            "max_abs_change": max_abs,
            "calendar_linked_count": linked,
            "typical_implication": typical_implication(sp, event_type, avg_change, linked),
            "representative_cases": sorted(cases, key=lambda x: abs(x.get("change", 0) or 0), reverse=True)[:3],
        })
    return sorted(out, key=lambda x: (x.get("species", ""), -x.get("case_count", 0)))


def typical_implication(sp: str, event_type: str, avg_change: float, linked: int) -> str:
    name = SPECIES_LABEL.get(sp, sp)
    if event_type == "signal_jump":
        base = f"{name} 상방 전환 시 견적 재확인·단기 물량 확보 검토"
    elif event_type == "signal_drop":
        base = f"{name} 하방 전환 시 추가 비축보다 필요 물량 중심 운영 검토"
    else:
        base = f"{name} 변동 사례 참고"
    if linked:
        base += " / 시즌·정책 이벤트와 함께 확인 필요"
    if abs(avg_change) >= 12:
        base += " / 평균 변동폭이 커서 보고 시 별도 코멘트 필요"
    return base


def species_comparison_summary(comparisons: list[dict], patterns: list[dict]) -> list[dict]:
    out = []
    for sp in SPECIES_ORDER:
        comps = [c for c in comparisons if c.get("species") == sp]
        pats = [p for p in patterns if p.get("species") == sp]
        out.append({
            "id": sp,
            "name": SPECIES_LABEL.get(sp, sp),
            "similar_case_count": len(comps),
            "high_similarity_count": sum(1 for c in comps if c.get("similarity_grade") == "high"),
            "pattern_count": len(pats),
            "top_similarity": comps[0] if comps else None,
            "top_pattern": sorted(pats, key=lambda x: x.get("case_count", 0), reverse=True)[0] if pats else None,
            "summary_note": summary_note(sp, comps, pats),
        })
    return out


def summary_note(sp: str, comps: list[dict], pats: list[dict]) -> str:
    name = SPECIES_LABEL.get(sp, sp)
    if not comps and not pats:
        return f"{name}은 비교 가능한 과거 사례가 부족"
    if comps and comps[0].get("similarity_grade") == "high":
        return f"{name} 현재 신호와 유사한 과거 사례가 높게 감지되어 구매 시사점 확인 필요"
    if pats:
        return f"{name} 과거 패턴은 보조 참고 가능하나 최신 공식자료와 병행 확인 필요"
    return f"{name} 유사사례는 제한적"


def main() -> int:
    scores = read_json(ANALYSIS / "evidence_scores.json", {"species": []})
    memory = read_json(ANALYSIS / "market_memory.json", {"items": []})
    comparisons = compare_current_to_cases(scores, memory)
    patterns = pattern_summary(memory)
    species_summary = species_comparison_summary(comparisons, patterns)

    payload = {
        "updated_at": now_iso(),
        "policy": "phase5_case_comparison_v1",
        "notice": "현재 시장신호와 과거 시장 메모리 사례를 비교한 검수용 자료입니다. 가격 예측이 아니라 과거 패턴 참고값입니다.",
        "summary": {
            "comparison_count": len(comparisons),
            "high_similarity_count": sum(1 for c in comparisons if c.get("similarity_grade") == "high"),
            "pattern_count": len(patterns),
            "species_count": len(species_summary),
        },
        "species": species_summary,
        "comparisons": comparisons,
        "patterns": patterns,
        "inputs": {
            "scores_policy": scores.get("policy"),
            "memory_policy": memory.get("policy"),
        },
    }
    write_json(ANALYSIS / "case_comparison.json", payload)
    write_json(ADMIN / "case_comparison.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

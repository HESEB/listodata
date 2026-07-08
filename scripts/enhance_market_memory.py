#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enhance Market Memory for HESEB Livestock Terminal.

Phase 5-2 connects:
- signal_history.json
- market_memory.json
- event_calendar.json
- evidence_scores.json
- conflict_report.json

Output:
- app/data/analysis/market_memory.json
- app/data/admin/market_memory.json

This is not a price prediction model. It is an operational memory layer that
summarizes past signal movements, nearby events, and purchase implications.
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
HISTORY = DATA / "history"
EVENTS = DATA / "events"

SPECIES_ORDER = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG", "OTHER"]
SPECIES_LABEL = {"BEEF":"한우","PORK":"돈육","POULTRY":"계육","DUCK":"오리","EGG":"계란","OTHER":"기타"}
EVENT_TYPE_LABEL = {
    "seasonal_demand":"시즌 수요",
    "holiday_demand":"명절 수요",
    "supply_risk":"공급 리스크",
    "disease_risk":"질병/방역 리스크",
    "policy_support":"정책/지원",
    "policy_check":"정책 확인",
    "demand_recovery":"수요 회복",
    "signal_jump":"신호 급등",
    "signal_drop":"신호 하락",
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


def parse_date(value: str):
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def date_distance(a: str, b: str) -> int | None:
    da = parse_date(a)
    db = parse_date(b)
    if not da or not db:
        return None
    return abs((da - db).days)


def rows_by_species(history_items: list[dict]) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for row in history_items:
        sp = row.get("species")
        if sp:
            out[sp].append(row)
    for sp in out:
        out[sp].sort(key=lambda x: x.get("date", ""))
    return out


def detect_signal_events(history_items: list[dict], existing_events: list[dict]) -> list[dict]:
    by_sp = rows_by_species(history_items)
    events = []
    seen = set()

    for ev in existing_events:
        key = (ev.get("date"), ev.get("species"), ev.get("event_type"), ev.get("change"))
        seen.add(key)
        events.append(dict(ev))

    for sp, rows in by_sp.items():
        for prev, cur in zip(rows, rows[1:]):
            delta = round((cur.get("signal_score", 0) or 0) - (prev.get("signal_score", 0) or 0), 1)
            if abs(delta) < 8:
                continue
            event_type = "signal_jump" if delta > 0 else "signal_drop"
            key = (cur.get("date"), sp, event_type, delta)
            if key in seen:
                continue
            events.append({
                "date": cur.get("date"),
                "species": sp,
                "name": SPECIES_LABEL.get(sp, sp),
                "event_type": event_type,
                "event_type_label": EVENT_TYPE_LABEL.get(event_type, event_type),
                "change": delta,
                "from_score": prev.get("signal_score", 0),
                "to_score": cur.get("signal_score", 0),
                "confidence_score": cur.get("confidence_score", 0),
                "conflict_severity": cur.get("conflict_severity", "none"),
                "memo": f"{SPECIES_LABEL.get(sp, sp)} 신호 {delta:+.1f}점 변동",
                "source": "signal_history",
            })
    return sorted(events, key=lambda x: (x.get("date", ""), x.get("species", "")))[-160:]


def nearby_calendar_events(memory_event: dict, calendar_items: list[dict], max_days: int = 21) -> list[dict]:
    date = memory_event.get("date")
    sp = memory_event.get("species")
    matches = []
    for item in calendar_items:
        if sp and sp not in (item.get("species") or []):
            continue
        d1 = date_distance(date, item.get("date_start"))
        d2 = date_distance(date, item.get("date_end") or item.get("date_start"))
        ds = [d for d in [d1, d2] if d is not None]
        if not ds:
            continue
        dist = min(ds)
        if dist <= max_days:
            matches.append({
                "event_id": item.get("id"),
                "title": item.get("title"),
                "event_type": item.get("event_type"),
                "event_type_label": EVENT_TYPE_LABEL.get(item.get("event_type"), item.get("event_type")),
                "date_start": item.get("date_start"),
                "date_end": item.get("date_end"),
                "impact_direction": item.get("impact_direction"),
                "impact_level": item.get("impact_level"),
                "distance_days": dist,
                "purchase_check": item.get("purchase_check"),
            })
    return sorted(matches, key=lambda x: (x.get("distance_days", 999), -(x.get("impact_level") or 0)))[:5]


def implication(event: dict, nearby: list[dict]) -> str:
    sp = event.get("species")
    name = SPECIES_LABEL.get(sp, sp)
    change = event.get("change", 0) or 0
    if event.get("event_type") == "signal_jump":
        base = f"{name} 상방 신호가 확대된 사례로, 단기 견적 재확인 및 운영 물량 선확보 검토 필요"
    elif event.get("event_type") == "signal_drop":
        base = f"{name} 하방 신호가 확대된 사례로, 추가 비축보다 필요 물량 중심 운영 검토 필요"
    else:
        base = f"{name} 시장 신호 변동 사례"
    if nearby:
        base += f" / 인접 이벤트: {nearby[0].get('title')}"
    if abs(change) >= 15:
        base += " / 변동폭 큼"
    return base


def build_enriched_events(memory_events: list[dict], calendar_items: list[dict]) -> list[dict]:
    enriched = []
    for ev in memory_events:
        near = nearby_calendar_events(ev, calendar_items)
        item = dict(ev)
        item["event_type_label"] = item.get("event_type_label") or EVENT_TYPE_LABEL.get(item.get("event_type"), item.get("event_type"))
        item["nearby_calendar_events"] = near
        item["purchase_implication"] = implication(item, near)
        item["memory_id"] = f"{item.get('species','X')}_{item.get('date','NA')}_{item.get('event_type','event')}_{str(item.get('change','0')).replace('.','_').replace('-','m')}"
        enriched.append(item)
    return enriched


def species_cases(enriched_events: list[dict], history_items: list[dict], scores: dict, conflicts: dict) -> list[dict]:
    score_map = {x.get("id"): x for x in scores.get("species", [])}
    conflict_map = {x.get("id"): x for x in conflicts.get("species", [])}
    out = []
    for sp in SPECIES_ORDER:
        events = [x for x in enriched_events if x.get("species") == sp]
        jumps = [x for x in events if x.get("event_type") == "signal_jump"]
        drops = [x for x in events if x.get("event_type") == "signal_drop"]
        avg_jump = round(sum(x.get("change", 0) for x in jumps) / len(jumps), 1) if jumps else 0
        avg_drop = round(sum(x.get("change", 0) for x in drops) / len(drops), 1) if drops else 0
        recent_rows = [x for x in history_items if x.get("species") == sp][-5:]
        latest = recent_rows[-1] if recent_rows else {}
        current = score_map.get(sp, {})
        conflict = conflict_map.get(sp, {})
        out.append({
            "id": sp,
            "name": SPECIES_LABEL.get(sp, sp),
            "event_count": len(events),
            "jump_count": len(jumps),
            "drop_count": len(drops),
            "avg_jump_change": avg_jump,
            "avg_drop_change": avg_drop,
            "latest_signal_score": latest.get("signal_score", current.get("signal_score", 0)),
            "latest_status": latest.get("status", current.get("status", "판단 유보")),
            "current_confidence": current.get("confidence_score", 0),
            "current_conflict": conflict.get("conflict_severity", current.get("conflict", {}).get("severity", "none")),
            "top_cases": sorted(events, key=lambda x: abs(x.get("change", 0) or 0), reverse=True)[:5],
            "memory_note": memory_note(sp, events, current),
        })
    return out


def memory_note(sp: str, events: list[dict], current: dict) -> str:
    name = SPECIES_LABEL.get(sp, sp)
    if not events:
        return f"{name}은 아직 누적 사례가 부족하여 현재 신호 중심으로 판단"
    current_dir = current.get("direction", "hold")
    if current_dir == "up":
        return f"{name} 현재 상방 신호와 과거 급등 사례를 함께 비교 필요"
    if current_dir == "down":
        return f"{name} 현재 하방 신호와 과거 하락 사례를 함께 비교 필요"
    if current_dir == "hold":
        return f"{name} 현재 판단 유보 상태로, 과거 사례보다 최신 공식자료 보강 우선"
    return f"{name}은 과거 변동 사례를 보조 참고자료로 활용"


def similar_cases(current_scores: dict, enriched_events: list[dict]) -> list[dict]:
    out = []
    for score in current_scores.get("species", []):
        sp = score.get("id")
        direction = score.get("direction")
        target_type = "signal_jump" if direction == "up" else ("signal_drop" if direction == "down" else None)
        if not target_type:
            continue
        candidates = [x for x in enriched_events if x.get("species") == sp and x.get("event_type") == target_type]
        candidates = sorted(candidates, key=lambda x: abs((x.get("to_score", 0) or 0) - (score.get("signal_score", 0) or 0)))[:3]
        for c in candidates:
            out.append({
                "species": sp,
                "name": SPECIES_LABEL.get(sp, sp),
                "current_status": score.get("status"),
                "current_signal_score": score.get("signal_score"),
                "case_date": c.get("date"),
                "case_change": c.get("change"),
                "case_memo": c.get("memo"),
                "purchase_implication": c.get("purchase_implication"),
            })
    return out[:30]


def main() -> int:
    history = read_json(HISTORY / "signal_history.json", {"items": []})
    base_memory = read_json(ANALYSIS / "market_memory.json", {"items": []})
    calendar = read_json(EVENTS / "event_calendar.json", {"items": []})
    scores = read_json(ANALYSIS / "evidence_scores.json", {"species": []})
    conflicts = read_json(ANALYSIS / "conflict_report.json", {"species": []})

    history_items = history.get("items", [])
    calendar_items = calendar.get("items", [])
    memory_events = detect_signal_events(history_items, base_memory.get("items", []))
    enriched = build_enriched_events(memory_events, calendar_items)
    species = species_cases(enriched, history_items, scores, conflicts)
    similar = similar_cases(scores, enriched)

    payload = {
        "updated_at": now_iso(),
        "policy": "phase5_market_memory_v2",
        "notice": "과거 신호 변동, 이벤트 캘린더, 현재 시장신호를 연결한 시장 메모리입니다. 가격 예측이 아니라 구매 판단 보조자료입니다.",
        "summary": {
            "memory_event_count": len(enriched),
            "species_with_cases": sum(1 for x in species if x.get("event_count", 0) > 0),
            "calendar_linked_count": sum(1 for x in enriched if x.get("nearby_calendar_events")),
            "similar_case_count": len(similar),
        },
        "species": species,
        "similar_cases": similar,
        "items": enriched,
        "inputs": {
            "history_policy": history.get("policy"),
            "calendar_policy": calendar.get("policy"),
            "scores_policy": scores.get("policy"),
            "conflict_policy": conflicts.get("policy"),
        },
    }
    write_json(ANALYSIS / "market_memory.json", payload)
    write_json(ADMIN / "market_memory.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

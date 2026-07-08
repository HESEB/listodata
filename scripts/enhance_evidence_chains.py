#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enhance Evidence Chains for HESEB Livestock Terminal.

Phase 2-2 turns score outputs into causal chains:
source/evidence -> market impact -> risk/coverage -> suggested purchase action.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CLEAN = DATA / "clean"
ANALYSIS = DATA / "analysis"

SPECIES_ORDER = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG", "OTHER"]
SPECIES_LABEL = {"BEEF":"한우","PORK":"돈육","POULTRY":"계육","DUCK":"오리","EGG":"계란","OTHER":"기타"}
AXIS_LABEL = {"price":"가격","supply":"수급/도축","disease":"질병/방역","policy":"정책/고시","news":"뉴스/수요"}
AXIS_ORDER = ["price", "supply", "disease", "policy", "news"]

ACTION_MAP = {
    "BEEF": {"up":"정육류 비축 또는 고정가 협의 검토", "neutral":"시세 확인 후 행사·명절 물량 중심 선별 매입", "down":"단기 비축 확대보다 필요 물량 중심 운영", "hold":"공식 지표 추가 확인 후 판단"},
    "PORK": {"up":"후지·등심 등 하부위 비축/견적 재점검", "neutral":"부위별 수요와 냉동재고 확인 후 분할 매입", "down":"단기 매입 확대보다 가격 하락 확인 후 집행", "hold":"ASF·도축·가격 공식자료 추가 확인"},
    "POULTRY": {"up":"가슴살·안심·조각정육 단기 확보 검토", "neutral":"성수기 수요와 도계량을 보며 분할 확보", "down":"고정계약 물량 중심 운영 및 추가매입 보류", "hold":"도계량·AI 공식자료 추가 확인"},
    "DUCK": {"up":"행사물량 중심 견적 재확인 및 대체처 확보", "neutral":"행사수요·AI·도축량 확인 후 필요 물량 운영", "down":"추가 비축보다 행사 확정 물량 중심 운영", "hold":"오리 도축·AI 자료 보강 후 판단"},
    "EGG": {"up":"계란 가격·산란계·AI 이슈 확인 후 원가 영향 점검", "neutral":"가격안정 정책과 산란계 흐름 관찰", "down":"정책 효과와 가격 안정 여부 확인", "hold":"계란 가격·산란계 자료 추가 확인"},
    "OTHER": {"up":"공통 변수의 축종별 전이 가능성 확인", "neutral":"수입·환율·사료·물류 보조지표 관찰", "down":"공통 하방 요인 반영 여부 확인", "hold":"공통자료 보강 후 판단"},
}

IMPACT_MAP = {
    "price": {"up":"가격 상승 압력", "down":"가격 하락 또는 안정 요인", "neutral":"가격 보조 신호"},
    "supply": {"up":"공급 축소 또는 출하 제한 가능성", "down":"공급 확대 또는 수급 완화 가능성", "neutral":"수급 방향 추가 확인 필요"},
    "disease": {"up":"방역·이동제한·살처분에 따른 공급 리스크", "down":"질병 리스크 완화 가능성", "neutral":"질병 변수 보조 확인"},
    "policy": {"up":"정책·점검·지원 이슈에 따른 시장 변동성", "down":"가격안정·수입 확대 등 완충 요인", "neutral":"정책 보조 신호"},
    "news": {"up":"수요 증가 또는 이슈성 상방 신호", "down":"소비 둔화 또는 할인·완화 신호", "neutral":"뉴스 보조 신호"},
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


def pick_examples(items: list[dict], species: str, axis: str, limit: int = 3) -> list[dict]:
    matched = []
    for item in items:
        if species not in (item.get("species") or []):
            continue
        if item.get("evidence_axis") != axis:
            continue
        matched.append(item)
    matched.sort(key=lambda x: (x.get("source_level", 0), x.get("freshness_score", 0), x.get("quality_score", 0)), reverse=True)
    out = []
    for it in matched[:limit]:
        out.append({
            "title": it.get("title", ""),
            "published_at": it.get("published_at") or it.get("date"),
            "source": it.get("publisher") or it.get("source_title") or it.get("source_domain") or "",
            "source_level": it.get("source_level", 0),
            "quality_score": it.get("quality_score", 0),
            "direction": it.get("market_direction", "neutral"),
            "direction_label": it.get("market_direction_label", "중립/보조"),
            "url": it.get("url") or it.get("source_url") or "",
        })
    return out


def missing_axes(axis_detail: dict) -> list[str]:
    return [AXIS_LABEL[k] for k in AXIS_ORDER if not axis_detail.get(k, {}).get("items")]


def axis_chain_node(species: str, axis: str, detail: dict, examples: list[dict]) -> dict:
    up = detail.get("up", 0)
    down = detail.get("down", 0)
    direction = "up" if up > down else ("down" if down > up else "neutral")
    score = detail.get("score", 0)
    max_score = detail.get("max_score", 0)
    return {
        "axis": axis,
        "label": AXIS_LABEL.get(axis, axis),
        "score": score,
        "max_score": max_score,
        "items": detail.get("items", 0),
        "direction": direction,
        "market_impact": IMPACT_MAP.get(axis, {}).get(direction, "보조 신호"),
        "causal_step": causal_step(axis, direction),
        "evidence_examples": examples,
        "confidence_note": confidence_note(score, max_score, len(examples)),
    }


def causal_step(axis: str, direction: str) -> str:
    if axis == "disease":
        return "질병·방역 이슈 → 이동제한/살처분/심리 리스크 → 공급 변동성"
    if axis == "supply":
        return "도축·도계·출하 흐름 → 공급 가능량 변화 → 가격 방향성"
    if axis == "price":
        return "가격·시세 변화 → 원가 부담 변화 → 매입 타이밍 판단"
    if axis == "policy":
        return "정부·공식기관 정책 → 수급 안정/규제/지원 변수 → 단기 변동성"
    return "뉴스·수요 이벤트 → 소비/행사/시장심리 → 보조 판단"


def confidence_note(score: int, max_score: int, examples: int) -> str:
    if examples == 0 or max_score == 0:
        return "직접 연결 근거 부족"
    ratio = score / max_score
    if ratio >= 0.7:
        return "근거 연결 강함"
    if ratio >= 0.4:
        return "근거 일부 연결"
    return "보조 근거 수준"


def final_action(species: str, direction: str) -> str:
    return ACTION_MAP.get(species, ACTION_MAP["OTHER"]).get(direction, "추가 확인 필요")


def build_enhanced_chain(score: dict, clean_items: list[dict]) -> dict:
    sp = score.get("id")
    axis_detail = score.get("axis_detail") or {}
    nodes = []
    for axis in AXIS_ORDER:
        detail = axis_detail.get(axis) or {}
        examples = pick_examples(clean_items, sp, axis)
        nodes.append(axis_chain_node(sp, axis, detail, examples))

    missing = missing_axes(axis_detail)
    direction = score.get("direction", "hold")
    status = score.get("status", "판단 유보")
    confidence = score.get("confidence_score", 0)
    coverage = score.get("coverage_rate", 0)
    signal = score.get("signal_score", 0)

    if direction == "up":
        final_signal = "상방성 근거 우세"
    elif direction == "down":
        final_signal = "하방성 근거 우세"
    elif direction == "neutral":
        final_signal = "상·하방 근거 혼재"
    else:
        final_signal = "판단 유보"

    return {
        "id": sp,
        "name": score.get("name") or SPECIES_LABEL.get(sp, sp),
        "status": status,
        "direction": direction,
        "signal_score": signal,
        "confidence_score": confidence,
        "coverage_rate": coverage,
        "reason": score.get("reason", ""),
        "summary_chain": [
            {"step": "1. 자료 수집", "value": f"{score.get('evidence_count', 0)}건", "meaning": "축종 관련 정제자료 수"},
            {"step": "2. 근거 분류", "value": "가격·수급·질병·정책·뉴스/수요", "meaning": "5개 분석축으로 재분류"},
            {"step": "3. 시장 영향", "value": final_signal, "meaning": score.get("reason", "")},
            {"step": "4. 신뢰도", "value": f"{confidence}점 / 커버리지 {coverage}%", "meaning": "출처·최신성·공식자료·근거범위 종합"},
            {"step": "5. 구매전략", "value": final_action(sp, direction), "meaning": "현 데이터 기준 참고 액션"},
        ],
        "axis_nodes": nodes,
        "missing_evidence": missing,
        "hold_reason": hold_reason(score, missing),
        "purchase_action": final_action(sp, direction),
        "chain_policy": "phase2_evidence_chain_v2",
    }


def hold_reason(score: dict, missing: list[str]) -> str:
    if score.get("direction") != "hold":
        if missing:
            return "일부 근거축 부족: " + ", ".join(missing)
        return "주요 근거축 연결"
    reasons = []
    if score.get("evidence_count", 0) == 0:
        reasons.append("근거자료 없음")
    if score.get("coverage_rate", 0) < 35:
        reasons.append("커버리지 부족")
    if score.get("confidence_score", 0) < 40:
        reasons.append("신뢰도 부족")
    if missing:
        reasons.append("누락 근거: " + ", ".join(missing))
    return " / ".join(reasons) if reasons else "판단 유보"


def main() -> int:
    clean_items = read_json(CLEAN / "events_clean.json", {"items": []}).get("items", [])
    scores = read_json(ANALYSIS / "evidence_scores.json", {"species": []})
    enhanced = [build_enhanced_chain(score, clean_items) for score in scores.get("species", [])]
    payload = {
        "updated_at": now_iso(),
        "policy": "phase2_evidence_chain_v2",
        "notice": "뉴스/공식자료 → 근거축 → 시장영향 → 신뢰도 → 구매전략으로 연결한 Evidence Chain입니다.",
        "items": enhanced,
    }
    write_json(ANALYSIS / "evidence_chains.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

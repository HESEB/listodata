#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enhance Cross Market Matrix.

Phase 2-4 builds a dynamic cross-species influence matrix using:
- evidence_scores.json
- evidence_chains.json
- conflict_report.json

It does not predict prices. It explains possible cross-market pressure for admin
review and later dashboard use.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ANALYSIS = DATA / "analysis"
ADMIN = DATA / "admin"

SPECIES_LABEL = {
    "BEEF": "한우",
    "PORK": "돈육",
    "POULTRY": "계육",
    "DUCK": "오리",
    "EGG": "계란",
    "OTHER": "기타",
}

BASE_RELATIONS = [
    {"from": "POULTRY", "to": "PORK", "kind": "substitution", "base_strength": 0.30, "memo": "계육 강세 시 돈육 일부 대체수요 가능"},
    {"from": "PORK", "to": "POULTRY", "kind": "substitution", "base_strength": 0.25, "memo": "돈육 강세 시 계육 대체수요 가능"},
    {"from": "BEEF", "to": "PORK", "kind": "substitution", "base_strength": 0.18, "memo": "한우 강세 시 돈육 대체수요 일부 가능"},
    {"from": "PORK", "to": "BEEF", "kind": "substitution", "base_strength": 0.10, "memo": "돈육 강세 시 한우 대체 영향은 제한적"},
    {"from": "DUCK", "to": "POULTRY", "kind": "avian_risk", "base_strength": 0.35, "memo": "오리·계육은 가금 질병 리스크를 공유"},
    {"from": "POULTRY", "to": "DUCK", "kind": "avian_risk", "base_strength": 0.30, "memo": "계육·오리는 AI 방역 이슈의 전이 가능성 존재"},
    {"from": "EGG", "to": "POULTRY", "kind": "avian_risk", "base_strength": 0.28, "memo": "계란·계육은 산란계/가금 질병 이슈를 공유"},
    {"from": "POULTRY", "to": "EGG", "kind": "avian_risk", "base_strength": 0.25, "memo": "계육 방역 이슈는 계란 수급 심리에도 영향 가능"},
    {"from": "OTHER", "to": "BEEF", "kind": "common_factor", "base_strength": 0.16, "memo": "수입·환율·사료·물류 등 공통 변수 영향"},
    {"from": "OTHER", "to": "PORK", "kind": "common_factor", "base_strength": 0.18, "memo": "수입·환율·사료·물류 등 공통 변수 영향"},
    {"from": "OTHER", "to": "POULTRY", "kind": "common_factor", "base_strength": 0.18, "memo": "수입·환율·사료·물류 등 공통 변수 영향"},
]


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


def score_map(scores: dict) -> dict:
    return {x.get("id"): x for x in scores.get("species", [])}


def chain_map(chains: dict) -> dict:
    return {x.get("id"): x for x in chains.get("items", [])}


def conflict_map(conflicts: dict) -> dict:
    return {x.get("id"): x for x in conflicts.get("species", [])}


def direction_factor(direction: str) -> float:
    if direction == "up":
        return 1.0
    if direction == "down":
        return -0.65
    if direction == "hold":
        return 0.35
    return 0.15


def confidence_factor(confidence: int) -> float:
    if confidence >= 75:
        return 1.0
    if confidence >= 55:
        return 0.75
    if confidence >= 40:
        return 0.50
    return 0.30


def axis_overlap(from_score: dict, to_score: dict, kind: str) -> tuple[list[str], float]:
    f_axis = from_score.get("axis_detail") or {}
    t_axis = to_score.get("axis_detail") or {}
    shared = []
    bonus = 0.0
    for axis, label in [("price", "가격"), ("supply", "수급/도축"), ("disease", "질병/방역"), ("policy", "정책/고시"), ("news", "뉴스/수요")]:
        if f_axis.get(axis, {}).get("items") and t_axis.get(axis, {}).get("items"):
            shared.append(label)
            bonus += 0.04
    if kind == "avian_risk":
        f_disease = f_axis.get("disease", {}).get("items", 0)
        t_disease = t_axis.get("disease", {}).get("items", 0)
        if f_disease or t_disease:
            bonus += 0.12
            if "질병/방역" not in shared:
                shared.append("질병/방역")
    return shared, min(0.22, bonus)


def effect_label(value: float, source_direction: str) -> tuple[str, str]:
    if value >= 0.55:
        return "강한 전이", "high"
    if value >= 0.32:
        return "중간 전이", "medium"
    if value >= 0.15:
        return "약한 전이", "low"
    if value <= -0.20:
        return "완화/역방향", "inverse"
    if source_direction == "hold":
        return "판단유보 전이", "hold"
    return "관찰", "watch"


def relation_reason(rel: dict, from_score: dict, to_score: dict, shared_axes: list[str], from_conflict: dict) -> str:
    f_name = SPECIES_LABEL.get(rel["from"], rel["from"])
    t_name = SPECIES_LABEL.get(rel["to"], rel["to"])
    direction = from_score.get("status", "관찰")
    parts = [f"{f_name} {direction} 신호가 {t_name}에 전이 가능", rel.get("memo", "")]
    if shared_axes:
        parts.append("공통 근거축: " + ", ".join(shared_axes))
    if from_conflict.get("has_conflict"):
        parts.append("단, 원천 축종에 충돌 근거 존재")
    return " / ".join(parts)


def build_relation(rel: dict, scores: dict, conflicts: dict) -> dict:
    from_score = scores.get(rel["from"], {"id": rel["from"], "direction": "hold", "signal_score": 0, "confidence_score": 0})
    to_score = scores.get(rel["to"], {"id": rel["to"], "direction": "hold", "signal_score": 0, "confidence_score": 0})
    from_conflict = conflicts.get(rel["from"], {})
    shared_axes, overlap_bonus = axis_overlap(from_score, to_score, rel["kind"])
    signal_strength = max(0, from_score.get("signal_score", 0)) / 100
    base = rel["base_strength"]
    conf = confidence_factor(from_score.get("confidence_score", 0))
    d_factor = direction_factor(from_score.get("direction"))
    conflict_penalty = 0.75 if from_conflict.get("conflict_severity") == "high" else (0.88 if from_conflict.get("has_conflict") else 1.0)
    value = round((base + overlap_bonus) * signal_strength * conf * d_factor * conflict_penalty, 3)
    label, severity = effect_label(value, from_score.get("direction"))
    return {
        "from": rel["from"],
        "from_name": SPECIES_LABEL.get(rel["from"], rel["from"]),
        "to": rel["to"],
        "to_name": SPECIES_LABEL.get(rel["to"], rel["to"]),
        "kind": rel["kind"],
        "effect": label,
        "severity": severity,
        "strength": value,
        "base_strength": rel["base_strength"],
        "source_direction": from_score.get("direction", "hold"),
        "source_status": from_score.get("status", "판단 유보"),
        "source_signal_score": from_score.get("signal_score", 0),
        "source_confidence": from_score.get("confidence_score", 0),
        "target_status": to_score.get("status", "관찰"),
        "shared_axes": shared_axes,
        "conflict_note": from_conflict.get("memo", ""),
        "memo": relation_reason(rel, from_score, to_score, shared_axes, from_conflict),
    }


def species_summary(items: list[dict]) -> dict:
    out = {}
    for sp in SPECIES_LABEL:
        incoming = [x for x in items if x["to"] == sp]
        outgoing = [x for x in items if x["from"] == sp]
        out[sp] = {
            "id": sp,
            "name": SPECIES_LABEL[sp],
            "incoming_count": len(incoming),
            "outgoing_count": len(outgoing),
            "incoming_strength": round(sum(abs(x["strength"]) for x in incoming), 3),
            "outgoing_strength": round(sum(abs(x["strength"]) for x in outgoing), 3),
            "top_incoming": sorted(incoming, key=lambda x: abs(x["strength"]), reverse=True)[:3],
            "top_outgoing": sorted(outgoing, key=lambda x: abs(x["strength"]), reverse=True)[:3],
        }
    return out


def main() -> int:
    scores = read_json(ANALYSIS / "evidence_scores.json", {"species": []})
    chains = read_json(ANALYSIS / "evidence_chains.json", {"items": []})
    conflicts = read_json(ANALYSIS / "conflict_report.json", {"species": []})
    smap = score_map(scores)
    cmap = conflict_map(conflicts)
    items = [build_relation(rel, smap, cmap) for rel in BASE_RELATIONS]
    payload = {
        "updated_at": now_iso(),
        "policy": "phase2_cross_market_matrix_v1",
        "notice": "축종 간 대체수요·가금 질병·공통 변수 전이 가능성을 Evidence Score와 Conflict 결과로 가중한 검수용 매트릭스입니다.",
        "items": items,
        "species_summary": species_summary(items),
        "inputs": {
            "scores_policy": scores.get("policy"),
            "chains_policy": chains.get("policy"),
            "conflict_policy": conflicts.get("policy"),
        },
    }
    write_json(ANALYSIS / "cross_market_matrix.json", payload)
    write_json(ADMIN / "cross_market_matrix.json", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

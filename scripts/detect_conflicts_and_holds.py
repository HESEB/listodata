#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Detect evidence conflicts and strengthen hold decisions.

Phase 2-3 adds:
- axis-level conflict detection
- species-level conflict severity
- hold decision reasons
- conflict_report.json for admin review
- annotations back into evidence_scores.json and evidence_chains.json
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
ADMIN = DATA / "admin"

SPECIES_ORDER = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG", "OTHER"]
SPECIES_LABEL = {"BEEF":"한우","PORK":"돈육","POULTRY":"계육","DUCK":"오리","EGG":"계란","OTHER":"기타"}
AXIS_LABEL = {"price":"가격","supply":"수급/도축","disease":"질병/방역","policy":"정책/고시","news":"뉴스/수요"}
AXIS_ORDER = ["price", "supply", "disease", "policy", "news"]


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


def collect_axis_items(clean_items: list[dict]) -> dict:
    bucket = {sp: {axis: [] for axis in AXIS_ORDER} for sp in SPECIES_ORDER}
    for item in clean_items:
        axis = item.get("evidence_axis") or "news"
        if axis not in AXIS_ORDER:
            axis = "news"
        for sp in item.get("species") or []:
            if sp in bucket:
                bucket[sp][axis].append(item)
    return bucket


def weighted_direction(items: list[dict]) -> dict:
    w = {"up": 0.0, "down": 0.0, "neutral": 0.0}
    examples = {"up": [], "down": [], "neutral": []}
    for item in items:
        d = item.get("market_direction") or "neutral"
        if d not in w:
            d = "neutral"
        weight = (item.get("impact_score", 1) or 1) * 0.45 + (item.get("quality_score", 0) or 0) / 100 * 2.0 + (item.get("source_level", 1) or 1) * 0.25
        w[d] += weight
        if len(examples[d]) < 3:
            examples[d].append({
                "title": item.get("title", ""),
                "source": item.get("publisher") or item.get("source_title") or item.get("source_domain") or "",
                "direction": d,
                "quality_score": item.get("quality_score", 0),
                "source_level": item.get("source_level", 0),
                "url": item.get("url") or item.get("source_url") or "",
            })
    return {"weights": {k: round(v, 2) for k, v in w.items()}, "examples": examples}


def axis_conflict(axis: str, items: list[dict]) -> dict:
    wd = weighted_direction(items)
    up = wd["weights"]["up"]
    down = wd["weights"]["down"]
    total = up + down + wd["weights"]["neutral"]
    has_conflict = up > 0 and down > 0 and min(up, down) / max(up, down) >= 0.35
    if has_conflict:
        severity = "high" if min(up, down) / max(up, down) >= 0.65 else "medium"
    else:
        severity = "none"
    dominant = "up" if up > down else ("down" if down > up else "neutral")
    return {
        "axis": axis,
        "label": AXIS_LABEL.get(axis, axis),
        "items": len(items),
        "has_conflict": has_conflict,
        "severity": severity,
        "dominant_direction": dominant,
        "weighted_direction": wd["weights"],
        "conflict_ratio": round(min(up, down) / max(up, down), 2) if max(up, down) > 0 else 0,
        "examples": wd["examples"],
        "memo": conflict_memo(axis, has_conflict, dominant, severity),
    }


def conflict_memo(axis: str, has_conflict: bool, dominant: str, severity: str) -> str:
    label = AXIS_LABEL.get(axis, axis)
    if has_conflict:
        return f"{label} 축에서 상방·하방 근거가 동시에 감지되어 {severity} 충돌로 분류"
    if dominant == "up":
        return f"{label} 축은 상방 근거 우세"
    if dominant == "down":
        return f"{label} 축은 하방 근거 우세"
    return f"{label} 축은 중립 또는 보조 근거 중심"


def species_conflict(sp: str, axis_reports: list[dict], score: dict) -> dict:
    conflict_axes = [x for x in axis_reports if x["has_conflict"]]
    high = [x for x in conflict_axes if x["severity"] == "high"]
    missing = [AXIS_LABEL[k] for k in AXIS_ORDER if not score.get("axis_detail", {}).get(k, {}).get("items")]
    conflict_penalty = len(high) * 18 + (len(conflict_axes) - len(high)) * 10
    coverage = score.get("coverage_rate", 0)
    confidence = score.get("confidence_score", 0)
    official = score.get("official_count", 0)
    evidence = score.get("evidence_count", 0)

    hold_reasons = []
    if evidence == 0:
        hold_reasons.append("근거자료 없음")
    if coverage < 35:
        hold_reasons.append("커버리지 부족")
    if confidence < 40:
        hold_reasons.append("신뢰도 부족")
    if official == 0 and confidence < 55:
        hold_reasons.append("공식자료 부족")
    if high:
        hold_reasons.append("상·하방 근거 강충돌")
    elif len(conflict_axes) >= 2:
        hold_reasons.append("복수 근거축 충돌")
    if len(missing) >= 3:
        hold_reasons.append("주요 근거축 다수 누락")

    adjusted_confidence = max(0, confidence - conflict_penalty)
    should_hold = bool(hold_reasons) and (adjusted_confidence < 55 or high or coverage < 35 or evidence == 0)

    if high:
        severity = "high"
    elif conflict_axes:
        severity = "medium"
    elif hold_reasons:
        severity = "low"
    else:
        severity = "none"

    return {
        "id": sp,
        "name": SPECIES_LABEL.get(sp, sp),
        "has_conflict": bool(conflict_axes),
        "conflict_severity": severity,
        "conflict_axes": [x["label"] for x in conflict_axes],
        "missing_evidence": missing,
        "hold_reasons": hold_reasons,
        "original_confidence": confidence,
        "adjusted_confidence": adjusted_confidence,
        "should_hold": should_hold,
        "recommended_status": "판단 유보" if should_hold else score.get("status", "보합/혼조"),
        "recommended_direction": "hold" if should_hold else score.get("direction", "neutral"),
        "memo": species_memo(conflict_axes, missing, hold_reasons, should_hold),
    }


def species_memo(conflict_axes: list[dict], missing: list[str], hold_reasons: list[str], should_hold: bool) -> str:
    parts = []
    if conflict_axes:
        parts.append("충돌축: " + ", ".join(x["label"] for x in conflict_axes))
    if missing:
        parts.append("누락근거: " + ", ".join(missing))
    if hold_reasons:
        parts.append("유보사유: " + ", ".join(hold_reasons))
    if not parts:
        return "충돌 또는 판단 유보 요인 없음"
    return ("판단 유보 권장 · " if should_hold else "주의 필요 · ") + " / ".join(parts)


def annotate_scores(scores: dict, conflicts: dict) -> dict:
    scores = dict(scores)
    out = []
    for score in scores.get("species", []):
        sp = score.get("id")
        c = conflicts.get(sp)
        if c:
            score = dict(score)
            score["conflict"] = {
                "has_conflict": c["has_conflict"],
                "severity": c["conflict_severity"],
                "axes": c["conflict_axes"],
                "memo": c["memo"],
            }
            score["hold_decision"] = {
                "should_hold": c["should_hold"],
                "reasons": c["hold_reasons"],
                "recommended_status": c["recommended_status"],
                "recommended_direction": c["recommended_direction"],
                "adjusted_confidence": c["adjusted_confidence"],
            }
            if c["should_hold"]:
                score["direction"] = "hold"
                score["status"] = "판단 유보"
                score["confidence_score"] = c["adjusted_confidence"]
        out.append(score)
    scores["species"] = out
    scores["conflict_policy"] = "phase2_conflict_hold_v1"
    return scores


def annotate_chains(chains: dict, conflicts: dict, axis_conflicts: dict) -> dict:
    chains = dict(chains)
    out = []
    for chain in chains.get("items", []):
        sp = chain.get("id")
        c = conflicts.get(sp)
        chain = dict(chain)
        if c:
            chain["conflict"] = c
            chain["axis_conflicts"] = axis_conflicts.get(sp, [])
            if c["should_hold"]:
                chain["status"] = "판단 유보"
                chain["direction"] = "hold"
                chain["hold_reason"] = c["memo"]
        out.append(chain)
    chains["items"] = out
    chains["conflict_policy"] = "phase2_conflict_hold_v1"
    return chains


def main() -> int:
    clean_items = read_json(CLEAN / "events_clean.json", {"items": []}).get("items", [])
    scores = read_json(ANALYSIS / "evidence_scores.json", {"species": []})
    chains = read_json(ANALYSIS / "evidence_chains.json", {"items": []})

    buckets = collect_axis_items(clean_items)
    axis_reports = {}
    species_reports = {}
    score_map = {x.get("id"): x for x in scores.get("species", [])}

    for sp in SPECIES_ORDER:
        reports = [axis_conflict(axis, buckets[sp][axis]) for axis in AXIS_ORDER]
        axis_reports[sp] = reports
        species_reports[sp] = species_conflict(sp, reports, score_map.get(sp, {"id": sp}))

    report = {
        "updated_at": now_iso(),
        "policy": "phase2_conflict_hold_v1",
        "notice": "상방·하방 근거 충돌, 근거 누락, 신뢰도 부족에 따른 판단 유보 검수 리포트입니다.",
        "summary": {
            "species_count": len(SPECIES_ORDER),
            "conflict_species_count": sum(1 for x in species_reports.values() if x["has_conflict"]),
            "hold_recommended_count": sum(1 for x in species_reports.values() if x["should_hold"]),
            "high_conflict_count": sum(1 for x in species_reports.values() if x["conflict_severity"] == "high"),
        },
        "species": list(species_reports.values()),
        "axis_reports": axis_reports,
    }

    write_json(ANALYSIS / "conflict_report.json", report)
    write_json(ANALYSIS / "evidence_scores.json", annotate_scores(scores, species_reports))
    write_json(ANALYSIS / "evidence_chains.json", annotate_chains(chains, species_reports, axis_reports))

    # Lightweight admin snapshot for dashboards that prefer admin folder.
    write_json(ADMIN / "conflict_report.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

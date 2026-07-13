#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build purchase recommendations from Direction Engine 2.0 outputs.

Phase 7-5 principles:
- Recommendations never bypass HOLD/coverage/confidence gates.
- Recommendations are market-data guidance until internal inventory/contract data exists.
- One primary action and up to two secondary actions are returned with reasons.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
DIRECTION_PATH = DATA / "analysis" / "direction_engine_v2.json"
POLICY_PATH = DATA / "design" / "recommendation_engine_policy.json"
ADMIN_OUT = DATA / "admin" / "recommendation_engine.json"
ANALYSIS_OUT = DATA / "analysis" / "recommendation_engine.json"


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


def species_rows(doc: dict) -> list[dict]:
    rows = doc.get("species", []) if isinstance(doc, dict) else []
    if isinstance(rows, dict):
        return [dict(v, species=k) if isinstance(v, dict) else {"species": k} for k, v in rows.items()]
    return [x for x in rows if isinstance(x, dict)]


def action_info(code: str, policy: dict) -> dict:
    meta = policy.get("actions", {}).get(code, {})
    return {
        "code": code,
        "label": meta.get("label", code),
        "priority": meta.get("priority", 9),
    }


def confidence_band(score: float, policy: dict) -> str:
    cfg = policy.get("confidence_adjustments", {})
    if score >= float(cfg.get("high_min", 80)):
        return "high"
    if score >= float(cfg.get("medium_min", 65)):
        return "medium"
    if score >= float(cfg.get("low_min", 55)):
        return "low"
    return "insufficient"


def top_signal_reason(signal: dict) -> str | None:
    name = signal.get("name") or signal.get("metric_id")
    adjusted = float(signal.get("adjusted_signal") or 0)
    if not name or abs(adjusted) < 1:
        return None
    direction = "상방 압력" if adjusted > 0 else "하방 압력"
    return f"{name} {direction} {abs(adjusted):.1f}"


def category_reasons(row: dict) -> list[str]:
    labels = {
        "price": "가격",
        "supply": "수급",
        "production": "도축·생산",
        "breeding": "사육",
        "import_stock": "수입·재고",
        "disease": "질병",
        "policy_demand": "정책·수요",
    }
    scores = row.get("category_scores", {}) if isinstance(row.get("category_scores"), dict) else {}
    ranked = sorted(scores.items(), key=lambda kv: abs(float(kv[1] or 0)), reverse=True)
    out = []
    for key, value in ranked[:3]:
        value = float(value or 0)
        if abs(value) < 5:
            continue
        out.append(f"{labels.get(key, key)} {'상방' if value > 0 else '하방'} {abs(value):.1f}")
    return out


def hold_result(row: dict, policy: dict, reasons: list[str]) -> dict:
    action = action_info("hold", policy)
    return {
        "species": row.get("species"),
        "label": row.get("label", row.get("species")),
        "recommendation_status": "hold",
        "primary_action": action,
        "secondary_actions": [],
        "urgency": "none",
        "direction_code": row.get("direction_code", "hold"),
        "direction_label": row.get("direction_label", "판단 유보"),
        "direction_symbol": row.get("direction_symbol", "?"),
        "direction_score": row.get("raw_score", 0),
        "confidence_score": row.get("confidence_score", 0),
        "coverage_score": row.get("coverage_score", 0),
        "confidence_band": "insufficient",
        "reasons": reasons[:3] or ["공식 데이터가 충분하지 않아 행동 추천을 보류합니다."],
        "limitations": [policy.get("internal_data", {}).get("display_notice", "시장 데이터 기준 추천"), "내부 재고·계약·수요 계획 미반영"],
        "evidence": {
            "direction_engine": "app/data/analysis/direction_engine_v2.json",
            "top_signals": row.get("top_signals", [])[:3],
            "hold_reasons": row.get("hold_reasons", []),
        },
    }


def evaluate(row: dict, policy: dict) -> dict:
    req = policy.get("input_requirements", {})
    coverage = float(row.get("coverage_score") or 0)
    confidence = float(row.get("confidence_score") or 0)
    status = str(row.get("decision_status") or "hold")
    hold_reasons = list(row.get("hold_reasons", []))
    if status != req.get("decision_status", "ready"):
        hold_reasons.append("Direction Engine 판단 유보")
    if coverage < float(req.get("coverage_min", 60)):
        hold_reasons.append("공식 데이터 커버리지 부족")
    if confidence < float(req.get("confidence_min", 55)):
        hold_reasons.append("추천 신뢰도 부족")
    hold_reasons = list(dict.fromkeys(hold_reasons))
    if hold_reasons:
        return hold_result(row, policy, hold_reasons)

    direction = str(row.get("direction_code") or "flat")
    rule = policy.get("direction_rules", {}).get(direction, policy.get("direction_rules", {}).get("flat", {}))
    primary_code = str(rule.get("primary", "wait"))
    secondary_codes = [str(x) for x in rule.get("secondary", [])]
    band = confidence_band(confidence, policy)

    conflicts = row.get("conflicts", []) if isinstance(row.get("conflicts"), list) else []
    if conflicts:
        primary_code = str(policy.get("signal_adjustments", {}).get("conflict_action", "wait"))
        secondary_codes = []

    if band == "low" and direction not in {"strong_up", "strong_down"}:
        primary_code = str(policy.get("confidence_adjustments", {}).get("low_confidence_action", "wait"))
        secondary_codes = []

    category_scores = row.get("category_scores", {}) if isinstance(row.get("category_scores"), dict) else {}
    price_score = float(category_scores.get("price") or 0)
    supply_score = float(category_scores.get("supply") or 0)
    import_stock = float(category_scores.get("import_stock") or 0)
    adj = policy.get("signal_adjustments", {})

    if direction in {"up", "strong_up"} and price_score >= float(adj.get("price_up_threshold", 20)):
        secondary_codes.insert(0, "fixed_price")
    if direction == "strong_up" and supply_score >= float(adj.get("supply_up_threshold", 20)):
        secondary_codes.insert(0, "stock_review")
    if direction in {"up", "strong_up"} and import_stock <= float(adj.get("import_stock_down_threshold", -20)):
        secondary_codes.insert(0, "substitute_review")

    deduped = []
    for code in secondary_codes:
        if code != primary_code and code not in deduped:
            deduped.append(code)
    max_secondary = int(policy.get("output_contract", {}).get("secondary_actions_max", 2))
    secondary = [action_info(code, policy) for code in deduped[:max_secondary]]

    reasons = category_reasons(row)
    for signal in row.get("top_signals", []) if isinstance(row.get("top_signals"), list) else []:
        reason = top_signal_reason(signal)
        if reason and reason not in reasons:
            reasons.append(reason)
    if conflicts:
        reasons.insert(0, "핵심지표 방향 충돌로 보수적 관망 추천")
    if not reasons:
        reasons.append(f"Direction Engine 결과 {row.get('direction_symbol', '=')} {row.get('direction_label', '보합')}")

    return {
        "species": row.get("species"),
        "label": row.get("label", row.get("species")),
        "recommendation_status": "ready",
        "primary_action": action_info(primary_code, policy),
        "secondary_actions": secondary,
        "urgency": rule.get("urgency", "low"),
        "direction_code": direction,
        "direction_label": row.get("direction_label"),
        "direction_symbol": row.get("direction_symbol"),
        "direction_score": row.get("raw_score", 0),
        "confidence_score": confidence,
        "coverage_score": coverage,
        "confidence_band": band,
        "reasons": reasons[:int(policy.get("output_contract", {}).get("reason_count_max", 3))],
        "limitations": [policy.get("internal_data", {}).get("display_notice", "시장 데이터 기준 추천"), "내부 재고·계약·수요 계획 미반영"],
        "evidence": {
            "direction_engine": "app/data/analysis/direction_engine_v2.json",
            "top_signals": row.get("top_signals", [])[:3],
            "category_scores": category_scores,
            "conflicts": conflicts,
        },
    }


def main() -> int:
    direction = read_json(DIRECTION_PATH, {"species": []})
    policy = read_json(POLICY_PATH, {})
    results = [evaluate(row, policy) for row in species_rows(direction)]
    ready = sum(1 for x in results if x.get("recommendation_status") == "ready")
    action_counts: dict[str, int] = {}
    for row in results:
        label = row.get("primary_action", {}).get("label", "-")
        action_counts[label] = action_counts.get(label, 0) + 1
    payload = {
        "updated_at": iso_now(),
        "policy": "phase7_recommendation_engine_v1",
        "summary": {
            "status": "ready" if ready == len(results) and results else ("partial" if ready else "hold"),
            "species_count": len(results),
            "ready_count": ready,
            "hold_count": len(results) - ready,
            "primary_action_counts": action_counts,
        },
        "species": results,
        "inputs": {
            "direction_engine": "app/data/analysis/direction_engine_v2.json",
            "policy": "app/data/design/recommendation_engine_policy.json"
        },
        "notice": policy.get("internal_data", {}).get("display_notice", "시장 데이터 기준 추천")
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

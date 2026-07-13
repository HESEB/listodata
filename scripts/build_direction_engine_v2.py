#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Direction Engine 2.0 results from official livestock metrics.

Phase 7-4 principles:
- Official numeric data drives direction.
- News does not directly create a direction score.
- Missing/low-quality data results in HOLD, never an invented direction.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CATALOG_PATH = DATA / "design" / "official_data_catalog.json"
POLICY_PATH = DATA / "design" / "direction_engine_v2_policy.json"
QUALITY_PATH = DATA / "analysis" / "official_data_quality.json"
SNAPSHOT_PATH = DATA / "official" / "snapshot" / "official_metrics_snapshot.json"
ADMIN_OUT = DATA / "admin" / "direction_engine_v2.json"
ANALYSIS_OUT = DATA / "analysis" / "direction_engine_v2.json"


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


def clamp(value: float, low: float = -100, high: float = 100) -> float:
    return max(low, min(high, value))


def round1(value: float) -> float:
    return round(value, 1)


def metric_map(snapshot_species: dict) -> dict[str, dict]:
    metrics = snapshot_species.get("metrics", {}) if isinstance(snapshot_species, dict) else {}
    if isinstance(metrics, dict):
        return {str(k): v for k, v in metrics.items() if isinstance(v, dict)}
    if isinstance(metrics, list):
        return {str(x.get("metric_id")): x for x in metrics if isinstance(x, dict) and x.get("metric_id")}
    return {}


def latest_record(record: dict) -> dict:
    if isinstance(record, dict) and isinstance(record.get("latest"), dict):
        return record["latest"]
    return record if isinstance(record, dict) else {}


def quality_species_map(doc: dict) -> dict[str, dict]:
    rows = doc.get("species", []) if isinstance(doc, dict) else []
    if isinstance(rows, dict):
        return rows
    return {str(x.get("species")): x for x in rows if isinstance(x, dict) and x.get("species")}


def band(score: float, policy: dict) -> dict:
    for row in policy.get("direction_bands", []):
        if float(row.get("min", -100)) <= score <= float(row.get("max", 100)):
            return {
                "code": row.get("code", "flat"),
                "label": row.get("label", "보합"),
                "symbol": row.get("symbol", "="),
            }
    return {"code": "flat", "label": "보합", "symbol": "="}


def category_group(category: str, policy: dict) -> str | None:
    for group, categories in policy.get("category_groups", {}).items():
        if category in categories:
            return group
    return None


def pressure_sign(metric_id: str, category: str, policy: dict) -> float:
    overrides = policy.get("metric_overrides", {})
    if metric_id in overrides:
        return float(overrides[metric_id])
    return float(policy.get("pressure_sign", {}).get(category, 0))


def comparison_signal(record: dict, metric_id: str, category: str, policy: dict) -> dict:
    comparisons = record.get("comparisons", {}) if isinstance(record.get("comparisons"), dict) else {}
    weights = policy.get("comparison_weights", {})
    sign = pressure_sign(metric_id, category, policy)
    points = []
    for key, weight in weights.items():
        comp = comparisons.get(key)
        if not isinstance(comp, dict) or comp.get("change_rate") is None:
            continue
        try:
            change_rate = float(comp.get("change_rate"))
        except (TypeError, ValueError):
            continue
        raw = math.tanh(change_rate / float(policy.get("change_rate_scale", {}).get("divisor", 8))) * 100
        points.append({
            "comparison": key,
            "change_rate": round1(change_rate),
            "weight": float(weight),
            "raw_signal": round1(raw),
            "pressure_signal": round1(raw * sign),
        })
    if not points or sign == 0:
        return {
            "usable": False,
            "signal": 0,
            "reason": "비교 변화율 없음" if not points else "방향 규칙 미정",
            "comparisons": points,
        }
    total_weight = sum(x["weight"] for x in points) or 1
    signal = sum(x["pressure_signal"] * x["weight"] for x in points) / total_weight
    return {"usable": True, "signal": round1(clamp(signal)), "reason": None, "comparisons": points}


def confidence_stars(score: float) -> int:
    if score >= 90:
        return 5
    if score >= 75:
        return 4
    if score >= 60:
        return 3
    if score >= 45:
        return 2
    return 1


def consistency_score(category_scores: dict[str, float], threshold: float) -> tuple[float, list[str]]:
    core = {k: v for k, v in category_scores.items() if k in {"price", "supply", "production", "breeding", "import_stock"} and abs(v) >= threshold}
    if len(core) <= 1:
        return 100.0, []
    positive = [k for k, v in core.items() if v > 0]
    negative = [k for k, v in core.items() if v < 0]
    if positive and negative:
        conflicts = [f"{a}↔{b}" for a in positive for b in negative]
        ratio = max(len(positive), len(negative)) / len(core)
        return round1(40 + ratio * 30), conflicts
    return 100.0, []


def evaluate_species(code: str, catalog_meta: dict, snapshot_meta: dict, quality_meta: dict, policy: dict) -> dict:
    records = metric_map(snapshot_meta)
    metric_specs = catalog_meta.get("required_metrics", [])
    metric_results = []
    category_values: dict[str, list[float]] = {}

    quality_metrics = {str(x.get("metric_id")): x for x in quality_meta.get("metrics", []) if isinstance(x, dict)}
    for spec in metric_specs:
        metric_id = str(spec.get("metric_id"))
        category = str(spec.get("category"))
        group = category_group(category, policy)
        record = latest_record(records.get(metric_id, {}))
        q = quality_metrics.get(metric_id, {})
        signal = comparison_signal(record, metric_id, category, policy) if record else {
            "usable": False, "signal": 0, "reason": "공식 데이터 없음", "comparisons": []
        }
        metric_quality = float(q.get("quality_score") or 0)
        adjusted_signal = signal["signal"] * metric_quality / 100 if signal["usable"] else 0
        result = {
            "metric_id": metric_id,
            "name": spec.get("name"),
            "category": category,
            "category_group": group,
            "priority": spec.get("priority", 2),
            "present": bool(record),
            "usable": bool(signal["usable"] and metric_quality >= 55),
            "raw_signal": signal["signal"],
            "quality_score": metric_quality,
            "adjusted_signal": round1(adjusted_signal),
            "reason": signal.get("reason") if not signal["usable"] else ("품질 55점 미만" if metric_quality < 55 else None),
            "comparisons": signal.get("comparisons", []),
        }
        metric_results.append(result)
        if result["usable"] and group:
            category_values.setdefault(group, []).append(result["adjusted_signal"])

    category_scores = {group: round1(sum(values) / len(values)) for group, values in category_values.items() if values}
    weights = policy.get("category_weights", {})
    used_weight = sum(float(weights.get(group, 0)) for group in category_scores)
    raw_score = (
        sum(category_scores[group] * float(weights.get(group, 0)) for group in category_scores) / used_weight
        if used_weight else 0
    )
    raw_score = round1(clamp(raw_score))

    required_count = len(metric_specs)
    usable_count = sum(1 for x in metric_results if x["usable"])
    usable_ratio = round1(usable_count / max(required_count, 1) * 100)
    consistency, conflicts = consistency_score(category_scores, float(policy.get("conflict_threshold", 20)))

    reliability = float(quality_meta.get("reliability_score") or 0)
    freshness = float(quality_meta.get("freshness_score") or 0)
    coverage = float(quality_meta.get("coverage_score") or 0)
    confidence_weights = policy.get("confidence_weights", {})
    news_alignment = float(policy.get("news_alignment_default", 0))
    confidence = (
        reliability * float(confidence_weights.get("official_reliability", 35))
        + freshness * float(confidence_weights.get("freshness", 25))
        + coverage * float(confidence_weights.get("coverage", 20))
        + consistency * float(confidence_weights.get("indicator_consistency", 15))
        + news_alignment * float(confidence_weights.get("news_alignment", 5))
    ) / 100
    confidence = round1(max(0, min(100, confidence)))

    hold_rules = policy.get("hold_rules", {})
    hold_reasons = list(quality_meta.get("hold_reasons", []))
    if coverage < float(hold_rules.get("coverage_below", 60)):
        hold_reasons.append("공식 데이터 커버리지 부족")
    if confidence < float(hold_rules.get("confidence_below", 55)):
        hold_reasons.append("방향 판단 신뢰도 부족")
    if usable_ratio < float(hold_rules.get("usable_indicator_ratio_below", 40)):
        hold_reasons.append("변화율이 있는 사용 가능 지표 부족")
    priority1_count = int(quality_meta.get("priority1_count") or 0)
    priority1_present = int(quality_meta.get("priority1_present_count") or 0)
    missing_ratio = round1((priority1_count - priority1_present) / max(priority1_count, 1) * 100)
    if missing_ratio > float(hold_rules.get("priority1_missing_ratio_above", 40)):
        hold_reasons.append("핵심지표 누락 비중 과다")
    if conflicts and bool(hold_rules.get("conflicting_core_categories", True)):
        hold_reasons.append("핵심지표 방향 충돌")
    hold_reasons = list(dict.fromkeys(hold_reasons))

    if hold_reasons:
        direction = {"code": "hold", "label": "판단 유보", "symbol": "?"}
        decision_status = "hold"
    else:
        direction = band(raw_score, policy)
        decision_status = "ready"

    strongest = sorted(metric_results, key=lambda x: abs(float(x.get("adjusted_signal") or 0)), reverse=True)
    return {
        "species": code,
        "label": catalog_meta.get("label", code),
        "decision_status": decision_status,
        "direction_code": direction["code"],
        "direction_label": direction["label"],
        "direction_symbol": direction["symbol"],
        "raw_score": raw_score,
        "confidence_score": confidence,
        "confidence_stars": confidence_stars(confidence),
        "coverage_score": coverage,
        "usable_indicator_count": usable_count,
        "required_indicator_count": required_count,
        "usable_indicator_ratio": usable_ratio,
        "indicator_consistency": consistency,
        "hold_reasons": hold_reasons,
        "conflicts": conflicts,
        "category_scores": category_scores,
        "top_signals": [x for x in strongest if x["usable"]][:3],
        "metric_signals": metric_results,
        "confidence_breakdown": {
            "official_reliability": reliability,
            "freshness": freshness,
            "coverage": coverage,
            "indicator_consistency": consistency,
            "news_alignment": news_alignment,
        },
    }


def main() -> int:
    catalog = read_json(CATALOG_PATH, {"species": {}})
    policy = read_json(POLICY_PATH, {})
    quality = read_json(QUALITY_PATH, {"species": []})
    snapshot = read_json(SNAPSHOT_PATH, {"species": {}})
    quality_map = quality_species_map(quality)
    results = []
    for code, meta in catalog.get("species", {}).items():
        results.append(evaluate_species(
            code,
            meta,
            snapshot.get("species", {}).get(code, {}),
            quality_map.get(code, {}),
            policy,
        ))

    ready_count = sum(1 for x in results if x["decision_status"] == "ready")
    payload = {
        "updated_at": iso_now(),
        "policy": "phase7_direction_engine_v2_v1",
        "summary": {
            "status": "ready" if ready_count == len(results) and results else ("partial" if ready_count else "hold"),
            "species_count": len(results),
            "ready_count": ready_count,
            "hold_count": len(results) - ready_count,
            "average_confidence": round1(sum(x["confidence_score"] for x in results) / max(len(results), 1)),
            "average_coverage": round1(sum(x["coverage_score"] for x in results) / max(len(results), 1)),
        },
        "species": results,
        "inputs": {
            "catalog": "app/data/design/official_data_catalog.json",
            "policy": "app/data/design/direction_engine_v2_policy.json",
            "quality": "app/data/analysis/official_data_quality.json",
            "snapshot": "app/data/official/snapshot/official_metrics_snapshot.json"
        },
        "notice": "공식 수치와 비교 변화율만 방향 점수에 사용합니다. 데이터 부족·품질 부족·핵심지표 충돌 시 판단 유보합니다."
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

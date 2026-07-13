#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build official data Quality, Coverage and Reliability outputs.

Phase 7-3 evaluates the Phase 7 official-data snapshot without inventing values.
It is safe when no official records are available: coverage becomes 0 and the
species is held from directional judgement.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CATALOG_PATH = DATA / "design" / "official_data_catalog.json"
POLICY_PATH = DATA / "design" / "official_data_quality_policy.json"
SNAPSHOT_PATH = DATA / "official" / "snapshot" / "official_metrics_snapshot.json"
ADMIN_OUT = DATA / "admin" / "official_data_quality.json"
ANALYSIS_OUT = DATA / "analysis" / "official_data_quality.json"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def clamp(value: float, low: float = 0, high: float = 100) -> float:
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


def band(score: float, bands: list[dict]) -> dict:
    ordered = sorted(bands, key=lambda x: float(x.get("min", 0)), reverse=True)
    for row in ordered:
        if score >= float(row.get("min", 0)):
            return {"code": row.get("code", "unknown"), "label": row.get("label", "-")}
    return {"code": "unknown", "label": "-"}


def expected_comparisons(metric_spec: dict) -> list[str]:
    aliases = {"7d": "week", "30d": "month"}
    return [aliases.get(str(x), str(x)) for x in metric_spec.get("comparisons", [])]


def latest_record(record: dict) -> dict:
    if not isinstance(record, dict):
        return {}
    if isinstance(record.get("latest"), dict):
        return record["latest"]
    return record


def evaluate_metric(spec: dict, record: dict | None, policy: dict) -> dict:
    priority = int(spec.get("priority", 2))
    frequency = str(spec.get("frequency", "monthly"))
    result = {
        "metric_id": spec.get("metric_id"),
        "name": spec.get("name"),
        "category": spec.get("category"),
        "priority": priority,
        "frequency": frequency,
        "present": bool(record),
        "value": None,
        "unit": None,
        "period_date": None,
        "age_days": None,
        "schema_validity": 0,
        "freshness_score": 0,
        "reliability_score": 0,
        "comparison_score": 0,
        "quality_score": 0,
        "status": "missing",
        "issues": [],
    }
    if not record:
        result["issues"].append("공식 데이터 없음")
        return result

    rec = latest_record(record)
    result["value"] = rec.get("value")
    result["unit"] = rec.get("unit")
    period = rec.get("period", {}) if isinstance(rec.get("period"), dict) else {}
    period_date = period.get("date") or rec.get("date")
    result["period_date"] = period_date

    required_ok = all([
        rec.get("metric_id") or spec.get("metric_id"),
        rec.get("species"),
        rec.get("category") or spec.get("category"),
        period_date,
        rec.get("value") is not None,
        rec.get("unit"),
        isinstance(rec.get("source"), dict),
    ])
    result["schema_validity"] = 100 if required_ok else 45
    if not required_ok:
        result["issues"].append("필수 필드 일부 누락")

    dt = parse_dt(period_date)
    if dt:
        age_days = max(0.0, (utcnow() - dt).total_seconds() / 86400)
        result["age_days"] = round1(age_days)
        threshold = float(policy.get("freshness_threshold_days", {}).get(frequency, 45))
        if age_days <= threshold:
            freshness = 100
        elif age_days <= threshold * 2:
            freshness = 70
        elif age_days <= threshold * 4:
            freshness = 40
        else:
            freshness = 10
            result["issues"].append("권장 최신성 기준 크게 초과")
        result["freshness_score"] = freshness
    else:
        result["issues"].append("기준일 확인 불가")

    source = rec.get("source", {}) if isinstance(rec.get("source"), dict) else {}
    source_level = str(source.get("source_level") or 1)
    source_scores = policy.get("reliability", {}).get("source_level_scores", {})
    reliability = float(source_scores.get(source_level, 30))
    provider = str(source.get("provider") or "")
    if "manual" in provider.lower() or "관리자" in provider:
        reliability = min(reliability, float(policy.get("reliability", {}).get("manual_approved_cap", 90)))
    quality = rec.get("quality", {}) if isinstance(rec.get("quality"), dict) else {}
    if quality.get("status") == "warning":
        reliability -= float(policy.get("reliability", {}).get("warning_penalty", 20))
    if rec.get("value") is None:
        reliability -= float(policy.get("reliability", {}).get("missing_value_penalty", 40))
    result["reliability_score"] = round1(clamp(reliability))

    expected = expected_comparisons(spec)
    comparisons = rec.get("comparisons", {}) if isinstance(rec.get("comparisons"), dict) else {}
    if expected:
        available = sum(1 for key in expected if isinstance(comparisons.get(key), dict) and comparisons[key].get("change_rate") is not None)
        result["comparison_score"] = round1(available / len(expected) * 100)
        if available < len(expected):
            result["issues"].append(f"비교지표 부족 {available}/{len(expected)}")
    else:
        result["comparison_score"] = 100

    weights = policy.get("quality_weights", {})
    score = (
        result["schema_validity"] * float(weights.get("schema_validity", 30))
        + result["freshness_score"] * float(weights.get("freshness", 30))
        + result["reliability_score"] * float(weights.get("source_reliability", 25))
        + result["comparison_score"] * float(weights.get("comparison_completeness", 15))
    ) / 100
    result["quality_score"] = round1(clamp(score))
    if result["quality_score"] >= 85:
        result["status"] = "excellent"
    elif result["quality_score"] >= 70:
        result["status"] = "good"
    elif result["quality_score"] >= 55:
        result["status"] = "limited"
    else:
        result["status"] = "risk"
    return result


def evaluate_species(code: str, catalog_species: dict, snapshot_species: dict, policy: dict) -> dict:
    specs = catalog_species.get("required_metrics", [])
    records = metric_map(snapshot_species)
    priority_weights = policy.get("coverage", {}).get("priority_weights", {"1": 2, "2": 1})
    evaluated = [evaluate_metric(spec, records.get(str(spec.get("metric_id"))), policy) for spec in specs]

    total_weight = sum(float(priority_weights.get(str(x.get("priority", 2)), 1)) for x in specs) or 1
    present_weight = sum(float(priority_weights.get(str(x["priority"]), 1)) for x in evaluated if x["present"])
    coverage = round1(present_weight / total_weight * 100)

    priority1 = [x for x in evaluated if x["priority"] == 1]
    priority1_present = [x for x in priority1 if x["present"]]
    priority1_coverage = round1(len(priority1_present) / max(len(priority1), 1) * 100)
    priority1_missing_ratio = round1(100 - priority1_coverage)

    present = [x for x in evaluated if x["present"]]
    quality_score = round1(sum(x["quality_score"] for x in present) / max(len(present), 1)) if present else 0
    reliability_score = round1(sum(x["reliability_score"] for x in present) / max(len(present), 1)) if present else 0
    freshness_score = round1(sum(x["freshness_score"] for x in present) / max(len(present), 1)) if present else 0

    gate = policy.get("confidence_gate", {})
    hold_reasons = []
    if coverage < float(gate.get("coverage_below", 60)):
        hold_reasons.append("공식 데이터 커버리지 부족")
    if quality_score < float(gate.get("quality_below", 55)):
        hold_reasons.append("공식 데이터 품질 부족")
    if priority1_missing_ratio > float(gate.get("priority1_missing_ratio_above", 40)):
        hold_reasons.append("핵심지표 누락 비중 과다")

    confidence = round1(coverage * 0.40 + quality_score * 0.35 + reliability_score * 0.25)
    quality_band = band(quality_score, policy.get("bands", {}).get("quality", []))
    coverage_band = band(coverage, policy.get("bands", {}).get("coverage", []))
    decision_status = "hold" if hold_reasons else "ready"

    return {
        "species": code,
        "label": catalog_species.get("label", code),
        "required_metric_count": len(specs),
        "present_metric_count": len(present),
        "priority1_count": len(priority1),
        "priority1_present_count": len(priority1_present),
        "coverage_score": coverage,
        "coverage_band": coverage_band,
        "priority1_coverage": priority1_coverage,
        "quality_score": quality_score,
        "quality_band": quality_band,
        "reliability_score": reliability_score,
        "freshness_score": freshness_score,
        "confidence_score": confidence,
        "decision_status": decision_status,
        "decision_label": "판단 가능" if decision_status == "ready" else "판단 유보",
        "hold_reasons": hold_reasons,
        "missing_priority1": [x["metric_id"] for x in priority1 if not x["present"]],
        "missing_metrics": [x["metric_id"] for x in evaluated if not x["present"]],
        "metrics": evaluated,
    }


def main() -> int:
    catalog = read_json(CATALOG_PATH, {"species": {}})
    policy = read_json(POLICY_PATH, {})
    snapshot = read_json(SNAPSHOT_PATH, {"species": {}})
    results = []
    for code, meta in catalog.get("species", {}).items():
        results.append(evaluate_species(code, meta, snapshot.get("species", {}).get(code, {}), policy))

    ready_count = sum(1 for x in results if x["decision_status"] == "ready")
    overall_coverage = round1(sum(x["coverage_score"] for x in results) / max(len(results), 1))
    overall_quality = round1(sum(x["quality_score"] for x in results) / max(len(results), 1))
    overall_reliability = round1(sum(x["reliability_score"] for x in results) / max(len(results), 1))
    overall_confidence = round1(sum(x["confidence_score"] for x in results) / max(len(results), 1))
    status = "ready" if ready_count == len(results) and results else ("partial" if ready_count else "hold")

    payload = {
        "updated_at": iso_now(),
        "policy": "phase7_official_data_quality_v1",
        "summary": {
            "status": status,
            "species_count": len(results),
            "ready_count": ready_count,
            "hold_count": len(results) - ready_count,
            "overall_coverage": overall_coverage,
            "overall_quality": overall_quality,
            "overall_reliability": overall_reliability,
            "overall_confidence": overall_confidence,
        },
        "species": results,
        "inputs": {
            "catalog": "app/data/design/official_data_catalog.json",
            "policy": "app/data/design/official_data_quality_policy.json",
            "snapshot": "app/data/official/snapshot/official_metrics_snapshot.json"
        },
        "notice": "공식 데이터가 부족한 축종은 점수를 임의 생성하지 않고 판단 유보로 처리합니다."
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

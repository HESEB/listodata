#!/usr/bin/env python3
"""Build market_metrics.json from public/source snapshot time-series.

Data quality rule:
- manual/sample snapshots must be shown as SAMPLE, not official actual data.
- adapter snapshots may be promoted to OFFICIAL only when the adapter reports success.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "app" / "data" / "source_snapshots" / "market_series_sample.json"
STATUS = ROOT / "app" / "data" / "source_snapshots" / "fetch_status.json"
OUTPUT = ROOT / "app" / "data" / "market_metrics.json"
KST = timezone(timedelta(hours=9))


def pct_change(current: Optional[float], base: Optional[float]) -> Optional[float]:
    if current is None or base in (None, 0):
        return None
    return round(((current - base) / base) * 100, 1)


def clamp(value: float, low: float = 0, high: float = 100) -> int:
    return int(max(low, min(high, round(value))))


def direction(change: Optional[float]) -> str:
    if change is None:
        return "flat"
    if change > 0.3:
        return "up"
    if change < -0.3:
        return "down"
    return "flat"


def interpret(label: str, change: Optional[float], unit: str, direction_value: str) -> str:
    if change is None:
        return "비교 기준값 추가 확보 필요"
    if unit == "%":
        if "공급" in label or "도축" in label or "도계" in label:
            if change <= -3:
                return "공급 감소 신호"
            if change >= 3:
                return "공급 증가 신호"
            return "공급 보합권"
        if change >= 3:
            return "가격 상승 압력 우세"
        if change <= -3:
            return "가격 하락 압력"
        return "가격 보합권"
    if unit == "점":
        if change >= 70:
            return "영향도 높음"
        if change >= 40:
            return "영향도 보통"
        return "영향도 낮음"
    if direction_value == "up":
        return "상승 신호"
    if direction_value == "down":
        return "하락 신호"
    return "보합권"


def get_yoy(values: List[Dict[str, Any]], current_month: str) -> Optional[Dict[str, Any]]:
    year, month = current_month.split("-")
    target = f"{int(year) - 1}-{month}"
    for row in values:
        if row.get("month") == target:
            return row
    return None


def load_fetch_status() -> Dict[str, str]:
    if not STATUS.exists():
        return {}
    try:
        data = json.loads(STATUS.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {row.get("source_id"): row.get("status") for row in data.get("sources", []) if row.get("source_id")}


def source_quality(source_ref: str, status_map: Dict[str, str]) -> Dict[str, str]:
    status = status_map.get(source_ref, "manual_snapshot_connected")
    if status == "adapter_success":
        return {"data_status": "OFFICIAL_FETCHED", "data_status_label": "공식수집"}
    if status in {"adapter_failed", "adapter_no_value"}:
        return {"data_status": "FETCH_FAILED", "data_status_label": "수집실패"}
    return {"data_status": "SAMPLE", "data_status_label": "샘플/수동"}


def score_signal(species_id: str, price_mom: Optional[float], supply_yoy: Optional[float], risks: Dict[str, Any]) -> int:
    score = 50.0
    if price_mom is not None:
        score += max(-15, min(20, price_mom * 3.5))
    if supply_yoy is not None:
        score += max(-15, min(20, -supply_yoy * 2.2))
    score += (float(risks.get("disease", 0)) - 25) * 0.10
    score += (float(risks.get("seasonal", 0)) - 40) * 0.12
    if species_id == "PORK":
        score -= (float(risks.get("stock_pressure", 0)) - 30) * 0.12
    return clamp(score)


def data_confidence(values: List[Dict[str, Any]], source_count: int, official_count: int) -> int:
    months = len(values)
    base = 25 + min(months, 18) * 1.4 + source_count * 5 + official_count * 18
    return clamp(base)


def metric(label: str, value: str, value_unit: str, change_label: str, change: Optional[float], change_unit: str, source_ref: str, status_map: Dict[str, str]) -> Dict[str, Any]:
    d = direction(change)
    q = source_quality(source_ref, status_map)
    return {
        "label": label,
        "value": value,
        "unit": value_unit,
        "change_label": change_label,
        "change": change,
        "change_unit": change_unit,
        "direction": d,
        "interpretation": interpret(label, change, change_unit, d),
        "source_ref": source_ref,
        **q,
    }


def build_metric_block(row: Dict[str, Any], status_map: Dict[str, str]) -> Dict[str, Any]:
    values = sorted(row.get("values", []), key=lambda x: x.get("month", ""))
    if not values:
        raise ValueError(f"No values for {row.get('id')}")

    latest = values[-1]
    prev = values[-2] if len(values) >= 2 else None
    yoy = get_yoy(values, latest["month"])

    price_mom = pct_change(latest.get("price"), prev.get("price") if prev else None)
    supply_mom = pct_change(latest.get("supply"), prev.get("supply") if prev else None)
    price_yoy = pct_change(latest.get("price"), yoy.get("price") if yoy else None)
    supply_yoy = pct_change(latest.get("supply"), yoy.get("supply") if yoy else None)
    risks = row.get("risk_factors", {}) or {}
    signal = score_signal(row["id"], price_mom, supply_yoy, risks)
    source_refs = [row.get("price_source_ref", "PRICE_SOURCE"), row.get("supply_source_ref", "SUPPLY_SOURCE")]
    official_count = sum(1 for ref in source_refs if status_map.get(ref) == "adapter_success")
    conf = data_confidence(values, len(source_refs), official_count)
    supply_unit = "수" if row["id"] == "POULTRY" else "두"

    metrics = [
        metric(row.get("price_metric", "가격"), f"{latest.get('price'):,}", "원/kg", "전월 대비", price_mom, "%", row.get("price_source_ref", "PRICE_SOURCE"), status_map),
        metric(row.get("supply_metric", "공급"), f"{latest.get('supply'):,}", supply_unit, "전월 대비", supply_mom, "%", row.get("supply_source_ref", "SUPPLY_SOURCE"), status_map),
        metric("가격 전년동월", "계산값", "%", "전년 대비", price_yoy, "%", row.get("price_source_ref", "PRICE_SOURCE"), status_map),
        metric("공급 전년동월", "계산값", "%", "전년 대비", supply_yoy, "%", row.get("supply_source_ref", "SUPPLY_SOURCE"), status_map),
        metric("계절 수요", "가중치", "점", "점수", float(risks.get("seasonal", 0)), "점", "SEASONAL_FACTOR", status_map),
        metric("질병 변수", "영향도", "점", "점수", float(risks.get("disease", 0)), "점", "DISEASE_FACTOR", status_map),
    ]

    data_statuses = {m["data_status"] for m in metrics[:2]}
    block_status = "OFFICIAL_FETCHED" if data_statuses == {"OFFICIAL_FETCHED"} else "SAMPLE_OR_PARTIAL"
    block_label = "공식수집" if block_status == "OFFICIAL_FETCHED" else "샘플/부분연동"

    summary_prefix = "공식 수집 데이터 기준" if block_status == "OFFICIAL_FETCHED" else "샘플/수동 스냅샷 기준"
    summary = (
        f"{summary_prefix} {latest['month']} {row.get('price_metric', '가격')}은 {latest.get('price'):,}원/kg, 전월 대비 {price_mom}%이며, "
        f"{row.get('supply_metric', '공급')}은 {latest.get('supply'):,}{supply_unit}, 전월 대비 {supply_mom}%입니다. "
        f"시장신호 점수는 {signal}점, 데이터 신뢰도는 {conf}점입니다."
    )

    return {
        "id": row["id"],
        "name": row.get("name", row["id"]),
        "basis_month": latest["month"],
        "signal_score": signal,
        "signal_score_unit": "점",
        "data_confidence": conf,
        "data_confidence_unit": "점",
        "data_status": block_status,
        "data_status_label": block_label,
        "metric_summary": summary,
        "metrics": metrics,
    }


def main() -> None:
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    status_map = load_fetch_status()
    species = [build_metric_block(row, status_map) for row in data.get("series", [])]
    output = {
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "notice": "핵심지표는 데이터 상태를 함께 표시합니다. 샘플/수동 스냅샷은 실제 공식수집값처럼 해석하지 마세요.",
        "unit_note": "가격은 원/kg, 도축두수는 두, 도계량은 수, 증감률은 %, 신호·신뢰도·영향도는 점으로 표시합니다.",
        "data_policy": "OFFICIAL_FETCHED만 공식 자동수집값이며, SAMPLE 또는 SAMPLE_OR_PARTIAL은 검증용/수동 입력값입니다.",
        "generated_by": "scripts/build_market_metrics.py",
        "species": species,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {len(species)} species")


if __name__ == "__main__":
    main()

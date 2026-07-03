#!/usr/bin/env python3
"""Build market_metrics.json from public/source snapshot time-series.

This script is intentionally dependency-free so it can run in GitHub Actions.
Current input is a sample/manual snapshot. Later, scraper/fetcher steps can replace
app/data/source_snapshots/market_series_sample.json with official data exports.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "app" / "data" / "source_snapshots" / "market_series_sample.json"
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
        return "전년 비교 기준값이 없어 추가 데이터 확보 필요"
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


def data_confidence(values: List[Dict[str, Any]], source_count: int = 2) -> int:
    months = len(values)
    return clamp(35 + min(months, 18) * 2.2 + source_count * 7)


def metric(label: str, value: str, value_unit: str, change_label: str, change: Optional[float], change_unit: str, source_ref: str) -> Dict[str, Any]:
    d = direction(change)
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
    }


def build_metric_block(row: Dict[str, Any]) -> Dict[str, Any]:
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
    conf = data_confidence(values)
    supply_unit = "수" if row["id"] == "POULTRY" else "두"

    metrics = [
        metric(row.get("price_metric", "가격"), f"{latest.get('price'):,}", "원/kg", "전월 대비", price_mom, "%", row.get("price_source_ref", "PRICE_SOURCE")),
        metric(row.get("supply_metric", "공급"), f"{latest.get('supply'):,}", supply_unit, "전월 대비", supply_mom, "%", row.get("supply_source_ref", "SUPPLY_SOURCE")),
        metric("가격 전년동월", "계산값", "%", "전년 대비", price_yoy, "%", row.get("price_source_ref", "PRICE_SOURCE")),
        metric("공급 전년동월", "계산값", "%", "전년 대비", supply_yoy, "%", row.get("supply_source_ref", "SUPPLY_SOURCE")),
        metric("계절 수요", "가중치", "점", "점수", float(risks.get("seasonal", 0)), "점", "SEASONAL_FACTOR"),
        metric("질병 변수", "영향도", "점", "점수", float(risks.get("disease", 0)), "점", "DISEASE_FACTOR"),
    ]

    summary = (
        f"{latest['month']} 기준 {row.get('price_metric', '가격')}은 {latest.get('price'):,}원/kg, 전월 대비 {price_mom}%이며, "
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
        "metric_summary": summary,
        "metrics": metrics,
    }


def main() -> None:
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    species = [build_metric_block(row) for row in data.get("series", [])]
    output = {
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "notice": "source_snapshots 시계열 기반으로 자동 계산된 핵심지표입니다. 현재 입력 데이터는 샘플/수동 스냅샷이며, 공식 데이터 자동수집 연결 전까지 참고용으로 사용합니다.",
        "unit_note": "가격은 원/kg, 도축두수는 두, 도계량은 수, 증감률은 %, 신호·신뢰도·영향도는 점으로 표시합니다.",
        "generated_by": "scripts/build_market_metrics.py",
        "species": species,
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {len(species)} species")


if __name__ == "__main__":
    main()

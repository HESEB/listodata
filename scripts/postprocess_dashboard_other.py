#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ensure OTHER/common market section exists after automatic data refresh."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
EVENTS = DATA / "events"
KST = timezone(timedelta(hours=9))


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def common_items() -> list[dict]:
    news = read_json(EVENTS / "events_news.json", {"items": []}).get("items", [])
    official = read_json(EVENTS / "events_official.json", {"items": []}).get("items", [])
    items = news + official
    out = []
    for it in items:
        species = it.get("species") or []
        title = it.get("title", "")
        doc = it.get("doc_type", "")
        if not species or "OTHER" in species or doc in {"NOTICE", "INDUSTRY", "PRODUCT", "GENERAL"}:
            out.append(it)
        elif any(k in title for k in ["수입", "환율", "사료", "물류", "소비", "정책", "식품", "유통", "가격 안정", "장바구니"]):
            out.append(it)
    return sorted(out, key=lambda x: x.get("published_at", x.get("date", "")), reverse=True)[:20]


def ensure_dashboard_other() -> None:
    path = DATA / "market_dashboard.json"
    dash = read_json(path, {})
    species = dash.setdefault("species", [])
    species = [x for x in species if x.get("id") != "OTHER"]
    items = common_items()
    facts = ["공통 정책·소비·수입·물류·사료 보조자료 확인", "개별 축종 외 시장 공통 변수 확인"]
    facts.extend([str(x.get("title", ""))[:42] for x in items[:3] if x.get("title")])
    other = {
        "id": "OTHER",
        "emoji": "📌",
        "name": "기타",
        "signal": "공통 변수 관찰",
        "confidence": "보통" if items else "낮음",
        "tone": "mixed" if items else "flat",
        "summary": "수입육, 환율, 사료, 물류, 소비동향, 정책자료 등 개별 축종에 직접 귀속되지 않는 공통 시장 변수를 확인합니다.",
        "facts": facts[:5],
        "indicators": [
            {"label": "공통자료", "value": f"{len(items)}건", "trend": "확인" if items else "보조"},
            {"label": "정책·소비", "value": "공통", "trend": "관찰"},
            {"label": "수입·물류·사료", "value": "보조", "trend": "확인"}
        ],
        "report_sentence": "기타 항목은 개별 축종 외 공통 변수인 수입육, 환율, 사료, 물류, 소비동향, 정책자료를 보조 근거로 확인하는 영역입니다."
    }
    species.append(other)
    dash["species"] = species
    write_json(path, dash)


def ensure_metrics_other() -> None:
    path = DATA / "market_metrics.json"
    metrics = read_json(path, {})
    species = metrics.setdefault("species", [])
    species = [x for x in species if x.get("id") != "OTHER"]
    items = common_items()
    species.append({
        "id": "OTHER",
        "basis_month": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "data_status": "OFFICIAL_FETCHED" if items else "FETCH_LIMITED",
        "data_status_label": "자동수집" if items else "수집제한",
        "data_confidence": 60 if items else 35,
        "signal_score": 55 if items else 40,
        "metric_summary": f"공통 정책·소비·수입·물류·사료 보조자료 {len(items)}건 기준입니다.",
        "metrics": [
            {"label":"공통자료", "value":len(items), "unit":"건", "change":55 if items else 40, "change_unit":"점", "direction":"mixed" if items else "flat", "interpretation":"공통 변수 관찰", "data_status":"OFFICIAL_FETCHED" if items else "FETCH_LIMITED", "data_status_label":"자동수집" if items else "수집제한"},
            {"label":"정책·소비", "value":"공통", "unit":"", "change":0, "change_unit":"점", "direction":"flat", "interpretation":"보조 판단", "data_status":"OFFICIAL_FETCHED", "data_status_label":"자동수집"}
        ]
    })
    metrics["species"] = species
    write_json(path, metrics)


def main() -> int:
    ensure_dashboard_other()
    ensure_metrics_other()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

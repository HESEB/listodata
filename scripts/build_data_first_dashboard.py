#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Phase 7-8 Data First Dashboard display contract.

This layer only combines outputs from Phase 7-3~7-7. It never invents a
market direction, recommendation, metric value, or news item.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
OUT = DATA / "display" / "data_first_dashboard.json"

PATHS = {
    "quality": DATA / "analysis" / "official_data_quality.json",
    "direction": DATA / "analysis" / "direction_engine_v2.json",
    "recommendation": DATA / "analysis" / "recommendation_engine.json",
    "news": DATA / "analysis" / "representative_news.json",
    "sentences": DATA / "analysis" / "report_sentence_engine.json",
}

ORDER = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG"]
LABELS = {"BEEF": "한우/우육", "PORK": "돈육", "POULTRY": "계육", "DUCK": "오리", "EGG": "계란"}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def rows_map(doc: dict) -> dict[str, dict]:
    rows = doc.get("species", []) if isinstance(doc, dict) else []
    if isinstance(rows, dict):
        return {str(k): v for k, v in rows.items() if isinstance(v, dict)}
    return {str(x.get("species")): x for x in rows if isinstance(x, dict) and x.get("species")}


def sentence_map(doc: dict) -> dict[str, dict]:
    rows = doc.get("species", []) if isinstance(doc, dict) else []
    if isinstance(rows, dict):
        return rows
    return {str(x.get("species")): x for x in rows if isinstance(x, dict) and x.get("species")}


def top_changes(direction: dict) -> list[dict]:
    out = []
    for row in direction.get("top_signals", []) if isinstance(direction.get("top_signals"), list) else []:
        out.append({
            "metric_id": row.get("metric_id"),
            "name": row.get("name") or row.get("metric_id"),
            "signal": row.get("adjusted_signal", 0),
            "quality_score": row.get("quality_score", 0),
            "comparisons": row.get("comparisons", []),
        })
    return out[:3]


def main() -> int:
    docs = {key: read_json(path, {}) for key, path in PATHS.items()}
    quality = rows_map(docs["quality"])
    direction = rows_map(docs["direction"])
    recommendation = rows_map(docs["recommendation"])
    news = rows_map(docs["news"])
    sentences = sentence_map(docs["sentences"])

    cards = []
    ready_count = 0
    for code in ORDER:
        q = quality.get(code, {})
        d = direction.get(code, {})
        r = recommendation.get(code, {})
        n = news.get(code, {})
        s = sentences.get(code, {})
        ready = d.get("decision_status") == "ready" and r.get("recommendation_status") == "ready"
        ready_count += int(ready)
        cards.append({
            "species": code,
            "label": d.get("label") or q.get("label") or LABELS[code],
            "status": "ready" if ready else "hold",
            "direction": {
                "code": d.get("direction_code", "hold"),
                "label": d.get("direction_label", "판단 유보"),
                "symbol": d.get("direction_symbol", "?"),
                "score": d.get("raw_score", 0),
            },
            "recommendation": {
                "primary": r.get("primary_action", {"code": "hold", "label": "판단 유보"}),
                "secondary": r.get("secondary_actions", []),
                "urgency": r.get("urgency", "none"),
                "reasons": r.get("reasons", []),
                "limitations": r.get("limitations", []),
            },
            "confidence": d.get("confidence_score", q.get("confidence_score", 0)),
            "confidence_stars": d.get("confidence_stars", 1),
            "coverage": q.get("coverage_score", d.get("coverage_score", 0)),
            "quality": q.get("quality_score", 0),
            "reliability": q.get("reliability_score", 0),
            "hold_reasons": d.get("hold_reasons", q.get("hold_reasons", [])),
            "top_changes": top_changes(d),
            "representative_news": n.get("representatives", [])[:2],
            "more_news_count": len(n.get("more", [])) if isinstance(n.get("more"), list) else 0,
            "report": {
                "summary": s.get("summary") or s.get("summary_sentence") or "",
                "manager": s.get("manager") or s.get("manager_sentence") or s.get("manager_report") or "",
                "executive": s.get("executive") or s.get("executive_sentence") or "",
            },
        })

    payload = {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "policy": "phase7_data_first_dashboard_v1",
        "summary": {
            "species_count": len(cards),
            "ready_count": ready_count,
            "hold_count": len(cards) - ready_count,
            "status": "ready" if ready_count == len(cards) else ("partial" if ready_count else "hold"),
        },
        "cards": cards,
        "display_contract": {
            "first_view": ["direction", "recommendation", "top_changes", "representative_news", "confidence", "coverage"],
            "detail_view": ["quality", "reliability", "hold_reasons", "report", "secondary_actions"],
        },
        "notice": "공식 데이터 중심 판단이며 내부 재고·계약·수요 계획은 아직 반영되지 않았습니다.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

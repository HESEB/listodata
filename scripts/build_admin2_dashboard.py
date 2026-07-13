#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Phase 7-9 Admin 2.0 integrated status document.

The output is intentionally read-only and combines the operational state of the
Phase 7 data-first pipeline without inventing missing values.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
OUT_ADMIN = DATA / "admin" / "admin2_dashboard.json"
OUT_ANALYSIS = DATA / "analysis" / "admin2_dashboard.json"

INPUTS = {
    "collection": DATA / "admin" / "official_data_collection.json",
    "structure": DATA / "admin" / "official_data_structure.json",
    "quality": DATA / "admin" / "official_data_quality.json",
    "direction": DATA / "admin" / "direction_engine_v2.json",
    "recommendation": DATA / "admin" / "recommendation_engine.json",
    "representative_news": DATA / "admin" / "representative_news.json",
    "context_filter": DATA / "admin" / "context_filter_v2.json",
    "report_sentence": DATA / "admin" / "report_sentence_engine.json",
    "freshness": DATA / "admin" / "freshness_alerts.json",
    "quality_alerts": DATA / "admin" / "quality_alerts.json",
    "update_stability": DATA / "admin" / "update_stability.json",
    "fallback": DATA / "admin" / "fallback_status.json",
}

SPECIES = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG"]
LABELS = {"BEEF": "한우/우육", "PORK": "돈육", "POULTRY": "계육", "DUCK": "오리", "EGG": "계란"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def species_map(doc: dict) -> dict[str, dict]:
    rows = doc.get("species", []) if isinstance(doc, dict) else []
    if isinstance(rows, dict):
        return {str(k): v for k, v in rows.items() if isinstance(v, dict)}
    return {str(x.get("species")): x for x in rows if isinstance(x, dict) and x.get("species")}


def summary_status(doc: dict, default: str = "pending") -> str:
    summary = doc.get("summary", {}) if isinstance(doc.get("summary"), dict) else {}
    return str(summary.get("status") or doc.get("status") or default)


def count_alerts(doc: dict) -> int:
    summary = doc.get("summary", {}) if isinstance(doc.get("summary"), dict) else {}
    for key in ("alert_count", "warning_count", "total_alerts", "critical_count"):
        try:
            return int(summary.get(key) or 0)
        except Exception:
            pass
    alerts = doc.get("alerts", [])
    return len(alerts) if isinstance(alerts, list) else 0


def main() -> int:
    docs = {name: read_json(path) for name, path in INPUTS.items()}
    quality = species_map(docs["quality"])
    direction = species_map(docs["direction"])
    recommendation = species_map(docs["recommendation"])
    news = species_map(docs["representative_news"])
    report = species_map(docs["report_sentence"])

    species_rows = []
    for code in SPECIES:
        q = quality.get(code, {})
        d = direction.get(code, {})
        r = recommendation.get(code, {})
        n = news.get(code, {})
        t = report.get(code, {})
        reps = n.get("representatives", []) if isinstance(n.get("representatives"), list) else []
        primary = r.get("primary_action", {}) if isinstance(r.get("primary_action"), dict) else {}
        hold_reasons = list(dict.fromkeys(
            list(q.get("hold_reasons", []) or [])
            + list(d.get("hold_reasons", []) or [])
            + (["추천 판단 유보"] if r.get("recommendation_status") == "hold" else [])
        ))
        species_rows.append({
            "species": code,
            "label": q.get("label") or d.get("label") or LABELS[code],
            "coverage_score": q.get("coverage_score", d.get("coverage_score", 0)),
            "quality_score": q.get("quality_score", 0),
            "reliability_score": q.get("reliability_score", 0),
            "freshness_score": q.get("freshness_score", 0),
            "confidence_score": d.get("confidence_score", q.get("confidence_score", 0)),
            "decision_status": d.get("decision_status", "hold"),
            "direction_symbol": d.get("direction_symbol", "?"),
            "direction_label": d.get("direction_label", "판단 유보"),
            "recommendation_status": r.get("recommendation_status", "hold"),
            "primary_action": primary.get("label", "판단 유보"),
            "representative_count": len(reps),
            "report_status": t.get("status") or t.get("sentence_status") or ("ready" if t else "pending"),
            "hold_reasons": hold_reasons[:5],
            "missing_priority1": q.get("missing_priority1", []),
        })

    ready_species = sum(1 for x in species_rows if x["decision_status"] == "ready")
    collection_summary = docs["collection"].get("summary", {}) if isinstance(docs["collection"].get("summary"), dict) else {}
    context_summary = docs["context_filter"].get("summary", {}) if isinstance(docs["context_filter"].get("summary"), dict) else {}
    rep_summary = docs["representative_news"].get("summary", {}) if isinstance(docs["representative_news"].get("summary"), dict) else {}

    stages = [
        {"code": "collection", "label": "공식 데이터 수집", "status": summary_status(docs["collection"]), "url": "./official-data-collector.html"},
        {"code": "quality", "label": "품질·커버리지", "status": summary_status(docs["quality"]), "url": "./official-data-quality.html"},
        {"code": "direction", "label": "Direction Engine", "status": summary_status(docs["direction"]), "url": "./direction-engine-v2.html"},
        {"code": "recommendation", "label": "Recommendation Engine", "status": summary_status(docs["recommendation"]), "url": "./recommendation-engine.html"},
        {"code": "representative_news", "label": "대표뉴스·문맥필터", "status": summary_status(docs["representative_news"]), "url": "./representative-news.html"},
        {"code": "report_sentence", "label": "Report Sentence", "status": summary_status(docs["report_sentence"]), "url": "./report-sentence-engine.html"},
    ]

    payload = {
        "updated_at": now_iso(),
        "policy": "phase7_admin2_dashboard_v1",
        "summary": {
            "status": "ready" if ready_species == len(SPECIES) else ("partial" if ready_species else "hold"),
            "species_count": len(SPECIES),
            "ready_species_count": ready_species,
            "hold_species_count": len(SPECIES) - ready_species,
            "active_source_count": collection_summary.get("active_source_count", 0),
            "collected_record_count": collection_summary.get("collected_count", 0),
            "representative_news_count": rep_summary.get("representative_count", 0),
            "context_rejected_count": context_summary.get("rejected_count", 0),
            "quality_alert_count": count_alerts(docs["quality_alerts"]),
            "freshness_alert_count": count_alerts(docs["freshness"]),
            "update_stability": summary_status(docs["update_stability"]),
            "fallback_status": summary_status(docs["fallback"]),
        },
        "pipeline_stages": stages,
        "species": species_rows,
        "review_queue": {
            "context_rejected_count": context_summary.get("rejected_count", 0),
            "quality_alert_count": count_alerts(docs["quality_alerts"]),
            "freshness_alert_count": count_alerts(docs["freshness"]),
            "hold_species": [
                {"species": x["species"], "label": x["label"], "reasons": x["hold_reasons"]}
                for x in species_rows if x["decision_status"] != "ready"
            ],
        },
        "inputs": {name: str(path.relative_to(ROOT)).replace("\\", "/") for name, path in INPUTS.items()},
        "notice": "Admin 2.0은 상태 검증 화면입니다. 내부 재고·계약·수요 계획이 연결되기 전 추천 결과는 시장 데이터 기준입니다.",
    }
    write_json(OUT_ADMIN, payload)
    write_json(OUT_ANALYSIS, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build DSS 2.0 report sentences from official data and analysis outputs.

Phase 7-7 principles:
- Official numeric metrics are the primary sentence source.
- Representative news is explanatory evidence only.
- HOLD results never become directional or purchasing claims.
- Output includes traceable evidence and explicit limitations.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY_PATH = DATA / "design" / "report_sentence_engine_policy.json"
CATALOG_PATH = DATA / "design" / "official_data_catalog.json"
SNAPSHOT_PATH = DATA / "official" / "snapshot" / "official_metrics_snapshot.json"
QUALITY_PATH = DATA / "analysis" / "official_data_quality.json"
DIRECTION_PATH = DATA / "analysis" / "direction_engine_v2.json"
RECOMMENDATION_PATH = DATA / "analysis" / "recommendation_engine.json"
NEWS_PATH = DATA / "analysis" / "representative_news.json"
ADMIN_OUT = DATA / "admin" / "report_sentence_engine.json"
ANALYSIS_OUT = DATA / "analysis" / "report_sentence_engine.json"


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


def rows_map(doc: dict, key: str = "species") -> dict[str, dict]:
    rows = doc.get(key, []) if isinstance(doc, dict) else []
    if isinstance(rows, dict):
        return {str(k): (v if isinstance(v, dict) else {}) for k, v in rows.items()}
    return {str(x.get("species")): x for x in rows if isinstance(x, dict) and x.get("species")}


def metric_map(snapshot_species: dict) -> dict[str, dict]:
    metrics = snapshot_species.get("metrics", {}) if isinstance(snapshot_species, dict) else {}
    if isinstance(metrics, dict):
        return {str(k): v for k, v in metrics.items() if isinstance(v, dict)}
    return {str(x.get("metric_id")): x for x in metrics if isinstance(x, dict) and x.get("metric_id")}


def latest_record(record: dict) -> dict:
    if isinstance(record, dict) and isinstance(record.get("latest"), dict):
        return record["latest"]
    return record if isinstance(record, dict) else {}


def fmt_number(value) -> str:
    if value is None:
        return "-"
    try:
        v = float(value)
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        if v.is_integer():
            return f"{v:.0f}"
        return f"{v:,.1f}"
    except Exception:
        return str(value)


def fmt_rate(value) -> str:
    try:
        v = float(value)
    except Exception:
        return ""
    arrow = "증가" if v > 0 else ("감소" if v < 0 else "보합")
    return f"{abs(v):.1f}% {arrow}"


def quality_metric_map(quality_row: dict) -> dict[str, dict]:
    return {
        str(x.get("metric_id")): x
        for x in quality_row.get("metrics", [])
        if isinstance(x, dict) and x.get("metric_id")
    }


def select_metrics(code: str, catalog_meta: dict, snapshot_meta: dict, quality_meta: dict, policy: dict) -> list[dict]:
    records = metric_map(snapshot_meta)
    qmap = quality_metric_map(quality_meta)
    priority = policy.get("comparison_priority", ["day", "month", "year"])
    results = []
    for spec in catalog_meta.get("required_metrics", []):
        metric_id = str(spec.get("metric_id"))
        rec = latest_record(records.get(metric_id, {}))
        q = qmap.get(metric_id, {})
        if not rec or rec.get("value") is None:
            continue
        quality_score = float(q.get("quality_score") or rec.get("quality", {}).get("reliability_score") or 0)
        if quality_score < float(policy.get("minimum_metric_quality", 55)):
            continue
        comps = rec.get("comparisons", {}) if isinstance(rec.get("comparisons"), dict) else {}
        chosen = None
        for key in priority:
            comp = comps.get(key)
            if isinstance(comp, dict) and comp.get("change_rate") is not None:
                chosen = {"key": key, **comp}
                break
        signal_strength = 0.0
        if chosen:
            try:
                signal_strength = abs(float(chosen.get("change_rate") or 0))
            except Exception:
                pass
        results.append({
            "metric_id": metric_id,
            "name": spec.get("name") or metric_id,
            "category": spec.get("category"),
            "priority": int(spec.get("priority", 2)),
            "value": rec.get("value"),
            "unit": rec.get("unit") or "",
            "period_date": (rec.get("period") or {}).get("date") if isinstance(rec.get("period"), dict) else rec.get("date"),
            "comparison": chosen,
            "quality_score": round(quality_score, 1),
            "signal_strength": round(signal_strength, 1),
            "provider": (rec.get("source") or {}).get("provider") if isinstance(rec.get("source"), dict) else None,
        })
    results.sort(key=lambda x: (x["priority"] == 1, x["signal_strength"], x["quality_score"]), reverse=True)
    return results[: int(policy.get("max_metric_mentions", 3))]


def metric_phrase(metric: dict, policy: dict) -> str:
    base = f"{metric['name']} {fmt_number(metric['value'])}{metric.get('unit') or ''}"
    comp = metric.get("comparison")
    if not comp:
        return base
    label = policy.get("comparison_labels", {}).get(comp.get("key"), comp.get("key", "비교"))
    return f"{base}({label} {fmt_rate(comp.get('change_rate'))})"


def news_map(doc: dict) -> dict[str, dict]:
    return rows_map(doc)


def recommendation_map(doc: dict) -> dict[str, dict]:
    return rows_map(doc)


def direction_map(doc: dict) -> dict[str, dict]:
    return rows_map(doc)


def quality_map(doc: dict) -> dict[str, dict]:
    return rows_map(doc)


def news_titles(row: dict, limit: int) -> list[dict]:
    out = []
    for item in row.get("representatives", []) if isinstance(row, dict) else []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        out.append({
            "title": item.get("title"),
            "publisher": item.get("publisher"),
            "url": item.get("url"),
            "representative_score": item.get("representative_score"),
        })
    return out[:limit]


def recommendation_label(row: dict) -> str:
    action = row.get("primary_action", {}) if isinstance(row, dict) else {}
    return action.get("label") or "판단 유보"


def build_species(code: str, catalog_meta: dict, snapshot_meta: dict, quality: dict, direction: dict, recommendation: dict, news: dict, policy: dict) -> dict:
    label = policy.get("species_labels", {}).get(code, catalog_meta.get("label", code))
    metrics = select_metrics(code, catalog_meta, snapshot_meta, quality, policy)
    representatives = news_titles(news, int(policy.get("max_news_mentions", 2)))
    hold = direction.get("decision_status") != "ready" or recommendation.get("recommendation_status") != "ready"
    direction_code = direction.get("direction_code", "hold")
    direction_label = direction.get("direction_label", "판단 유보")
    direction_symbol = direction.get("direction_symbol", "?")
    confidence = float(direction.get("confidence_score") or quality.get("confidence_score") or 0)
    coverage = float(direction.get("coverage_score") or quality.get("coverage_score") or 0)
    action = recommendation_label(recommendation)
    metric_text = ", ".join(metric_phrase(x, policy) for x in metrics)
    news_text = " / ".join(f"{x['title']}({x.get('publisher') or '출처 미상'})" for x in representatives)
    reasons = list(dict.fromkeys((recommendation.get("reasons") or []) + (direction.get("hold_reasons") or [])))

    if hold:
        core = policy.get("hold_sentence", "공식 데이터가 충분하지 않아 판단을 유보합니다.")
        if reasons:
            core += f" 주요 사유는 {', '.join(reasons[:3])}입니다."
        brief = f"[{label}] ? 판단 유보\n- 공식지표: {metric_text or '확보 중'}\n- 조치: {action}"
        manager = f"[{label}]\n{core}\n- 공식 데이터: {metric_text or '핵심지표 미확보'}\n- 신뢰도/커버리지: {confidence:.1f}% / {coverage:.1f}%\n- 구매 검토: {action}\n- 제한사항: {policy.get('internal_data_notice')}"
        executive = f"{label}: 공식 데이터 부족으로 판단 및 구매 행동 유보(신뢰도 {confidence:.0f}%, 커버리지 {coverage:.0f}%)."
        status = "hold"
    else:
        phrase = policy.get("direction_phrases", {}).get(direction_code, direction_label)
        data_clause = f"공식 데이터상 {metric_text}" if metric_text else "공식 데이터 변화지표상"
        news_clause = f" 대표 기사에서도 {news_text} 흐름이 확인됩니다." if news_text else ""
        core = f"{data_clause}가 확인되며, {label} 시장은 {phrase}.{news_clause}"
        brief = f"[{label}] {direction_symbol} {direction_label}\n- 핵심 변화: {metric_text or '비교지표 누적 중'}\n- 추천행동: {action}"
        manager = f"[{label}]\n{core}\n- 시장판단: {direction_symbol} {direction_label}\n- 신뢰도/커버리지: {confidence:.1f}% / {coverage:.1f}%\n- 대표 근거: {news_text or '대표 기사 없음'}\n- 구매 검토: {action}\n- 제한사항: {policy.get('internal_data_notice')}"
        executive = f"{label}: {direction_symbol} {direction_label}. 핵심 변화는 {metric_text or '공식 비교지표'}이며, {action} 검토가 필요합니다."
        status = "ready"

    return {
        "species": code,
        "label": label,
        "status": status,
        "direction_code": direction_code,
        "direction_label": direction_label,
        "direction_symbol": direction_symbol,
        "confidence_score": round(confidence, 1),
        "coverage_score": round(coverage, 1),
        "primary_action": action,
        "metrics": metrics,
        "representative_news": representatives,
        "reasons": reasons[:5],
        "sentences": {"brief": brief, "manager": manager, "executive": executive},
        "evidence_trace": {
            "official_snapshot": "app/data/official/snapshot/official_metrics_snapshot.json",
            "official_quality": "app/data/analysis/official_data_quality.json",
            "direction": "app/data/analysis/direction_engine_v2.json",
            "recommendation": "app/data/analysis/recommendation_engine.json",
            "representative_news": "app/data/analysis/representative_news.json"
        }
    }


def combined_report(results: list[dict], fmt: str) -> str:
    return "\n\n".join(x.get("sentences", {}).get(fmt, "") for x in results if x.get("sentences", {}).get(fmt))


def main() -> int:
    policy = read_json(POLICY_PATH, {})
    catalog = read_json(CATALOG_PATH, {"species": {}})
    snapshot = read_json(SNAPSHOT_PATH, {"species": {}})
    quality = quality_map(read_json(QUALITY_PATH, {"species": []}))
    directions = direction_map(read_json(DIRECTION_PATH, {"species": []}))
    recommendations = recommendation_map(read_json(RECOMMENDATION_PATH, {"species": []}))
    news = news_map(read_json(NEWS_PATH, {"species": []}))

    results = []
    for code in policy.get("species_order", []):
        results.append(build_species(
            code,
            catalog.get("species", {}).get(code, {}),
            snapshot.get("species", {}).get(code, {}),
            quality.get(code, {}),
            directions.get(code, {}),
            recommendations.get(code, {}),
            news.get(code, {}),
            policy,
        ))

    ready = sum(1 for x in results if x["status"] == "ready")
    payload = {
        "updated_at": iso_now(),
        "policy": "phase7_report_sentence_engine_v1",
        "summary": {
            "status": "ready" if ready == len(results) and results else ("partial" if ready else "hold"),
            "species_count": len(results),
            "ready_count": ready,
            "hold_count": len(results) - ready,
            "format_count": len(policy.get("formats", {}))
        },
        "formats": policy.get("formats", {}),
        "species": results,
        "reports": {
            "brief": combined_report(results, "brief"),
            "manager": combined_report(results, "manager"),
            "executive": combined_report(results, "executive")
        },
        "notice": policy.get("notice"),
        "limitations": [policy.get("internal_data_notice")]
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

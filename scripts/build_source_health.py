#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build source-level success/coverage report for HESEB Livestock Terminal.

Phase 6-6 summarizes source contribution and source health using existing
collected data, clean/rejected layers, quality report, and source registry.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ADMIN = DATA / "admin"
ANALYSIS = DATA / "analysis"

PATHS = {
    "source_links": DATA / "source_links.json",
    "raw": DATA / "raw" / "events_raw.json",
    "clean": DATA / "clean" / "events_clean.json",
    "rejected": DATA / "clean" / "events_rejected.json",
    "news": DATA / "events" / "events_news.json",
    "official": DATA / "events" / "events_official.json",
    "quality": ADMIN / "quality_report.json",
    "stability": ADMIN / "update_stability.json",
}

SOURCE_ALIASES = {
    "Google News": ["google", "news.google"],
    "KAHIS": ["kahis", "animal.go.kr"],
    "농림축산식품부": ["mafra", "m 농림", "농림축산식품부", "mifaff", "mafra.go.kr"],
    "축산물품질평가원": ["ekape", "축산물품질평가원", "축평원", "ekapepia"],
    "KREI": ["krei", "농촌경제연구원"],
    "HESEB 기준자료": ["heseb"],
}


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


def items_from(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["items", "events", "data"]:
            if isinstance(data.get(key), list):
                return data[key]
    return []


def source_name(item: dict) -> str:
    candidates = [
        item.get("provider"), item.get("publisher"), item.get("source"),
        item.get("source_name"), item.get("source_title"), item.get("site"),
        item.get("origin"), item.get("category"),
    ]
    url = str(item.get("url") or item.get("source_url") or "")
    text = " ".join(str(x or "") for x in candidates) + " " + url
    text_l = text.lower()
    for name, keys in SOURCE_ALIASES.items():
        if any(k.lower() in text_l for k in keys):
            return name
    for x in candidates:
        if x:
            return str(x)[:80]
    if url:
        return url.split("/")[2] if "/" in url else url[:80]
    return "Unknown"


def build_registry_sources(source_links: dict) -> dict[str, dict]:
    out = {}
    for group in source_links.get("groups", []) if isinstance(source_links, dict) else []:
        for item in group.get("items", []) or []:
            name = item.get("provider") or item.get("title") or "Unknown"
            out.setdefault(name, {
                "source": name,
                "registered": True,
                "titles": [],
                "groups": set(),
                "species": set(),
                "url_count": 0,
            })
            out[name]["titles"].append(item.get("title"))
            out[name]["groups"].add(group.get("title") or group.get("id") or "기타")
            for sp in item.get("species", []) or []:
                out[name]["species"].add(sp)
            out[name]["url_count"] += 1
    return out


def count_layer(rows: list[dict], layer: str, bucket: dict[str, dict]) -> None:
    for item in rows:
        name = source_name(item)
        row = bucket.setdefault(name, blank_source(name))
        row[layer] += 1
        q = item.get("quality_score")
        if isinstance(q, (int, float)):
            row["quality_scores"].append(q)
        for sp in item.get("species", []) or []:
            row["species"].add(sp)


def blank_source(name: str) -> dict:
    return {
        "source": name,
        "registered": False,
        "raw": 0,
        "clean": 0,
        "rejected": 0,
        "news": 0,
        "official": 0,
        "quality_scores": [],
        "species": set(),
        "groups": set(),
        "titles": [],
        "url_count": 0,
    }


def score_source(row: dict) -> dict:
    total = row["raw"] + row["news"] + row["official"]
    produced = row["clean"]
    rejected = row["rejected"]
    contribution = produced + row["official"]
    avg_quality = round(sum(row["quality_scores"]) / len(row["quality_scores"]), 1) if row["quality_scores"] else 0
    pass_rate = round(produced / max(produced + rejected, 1) * 100)
    coverage = round(contribution / max(total + produced + rejected, 1) * 100)
    health = 60
    if row["registered"]:
        health += 10
    if contribution > 0:
        health += 15
    if pass_rate >= 60:
        health += 10
    if avg_quality >= 60:
        health += 10
    if rejected > produced and rejected >= 5:
        health -= 20
    if total == 0 and produced == 0 and row["registered"]:
        health -= 15
    health = max(0, min(100, health))
    if health >= 85:
        grade, label = "healthy", "양호"
    elif health >= 65:
        grade, label = "watch", "관찰"
    else:
        grade, label = "risk", "위험"
    issues = []
    if row["registered"] and total == 0 and produced == 0:
        issues.append("등록되어 있으나 최근 기여 데이터 없음")
    if rejected > produced and rejected >= 5:
        issues.append("Rejected 비중 높음")
    if avg_quality and avg_quality < 45:
        issues.append("평균 품질점수 낮음")
    if not row["registered"]:
        issues.append("Source Center 미등록 출처")
    return {
        "source": row["source"],
        "registered": row["registered"],
        "groups": sorted(row["groups"]),
        "titles": [x for x in row["titles"] if x][:5],
        "species": sorted(row["species"]),
        "raw_count": row["raw"],
        "clean_count": row["clean"],
        "rejected_count": row["rejected"],
        "news_count": row["news"],
        "official_count": row["official"],
        "url_count": row["url_count"],
        "pass_rate": pass_rate,
        "coverage_rate": coverage,
        "avg_quality": avg_quality,
        "health_score": health,
        "health_grade": grade,
        "health_label": label,
        "issues": issues,
        "recommended_action": recommended_action(grade, issues),
    }


def recommended_action(grade: str, issues: list[str]) -> str:
    if grade == "healthy":
        return "정상 운영. 현재 수집/분류 기준 유지"
    if any("미등록" in x for x in issues):
        return "Source Center 등록 여부 검토"
    if any("Rejected" in x for x in issues):
        return "필터 사전 과차단 여부 및 분류검수 확인"
    if any("기여 데이터 없음" in x for x in issues):
        return "해당 출처 URL 또는 수집 쿼리 정상 동작 여부 확인"
    return "다음 자동 업데이트 후 추세 확인"


def main() -> int:
    source_links = read_json(PATHS["source_links"], {})
    bucket = {name: blank_source(name) for name in build_registry_sources(source_links).keys()}
    registry = build_registry_sources(source_links)
    for name, meta in registry.items():
        bucket[name].update(meta)

    count_layer(items_from(read_json(PATHS["raw"], {})), "raw", bucket)
    count_layer(items_from(read_json(PATHS["clean"], {})), "clean", bucket)
    count_layer(items_from(read_json(PATHS["rejected"], {})), "rejected", bucket)
    count_layer(items_from(read_json(PATHS["news"], {})), "news", bucket)
    count_layer(items_from(read_json(PATHS["official"], {})), "official", bucket)

    sources = sorted([score_source(row) for row in bucket.values()], key=lambda x: (x["health_score"], x["clean_count"] + x["official_count"]), reverse=True)
    summary = {
        "source_count": len(sources),
        "registered_count": sum(1 for x in sources if x["registered"]),
        "unregistered_count": sum(1 for x in sources if not x["registered"]),
        "healthy_count": sum(1 for x in sources if x["health_grade"] == "healthy"),
        "watch_count": sum(1 for x in sources if x["health_grade"] == "watch"),
        "risk_count": sum(1 for x in sources if x["health_grade"] == "risk"),
        "avg_health_score": round(sum(x["health_score"] for x in sources) / max(len(sources), 1), 1),
        "total_clean": sum(x["clean_count"] for x in sources),
        "total_rejected": sum(x["rejected_count"] for x in sources),
    }
    payload = {
        "updated_at": now_iso(),
        "policy": "phase6_source_health_v1",
        "notice": "수집 소스별 데이터 기여도, 통과율, Rejected 비율, Source Center 등록 여부를 요약한 관리자 리포트입니다.",
        "summary": summary,
        "sources": sources,
        "inputs": {k: "app/data/" + str(v.relative_to(DATA)).replace("\\", "/") for k, v in PATHS.items()},
    }
    write_json(ADMIN / "source_health.json", payload)
    write_json(ANALYSIS / "source_health.json", payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

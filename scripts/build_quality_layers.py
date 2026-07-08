#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Phase 1 data layers and quality scores for HESEB Livestock Terminal.

This script does not replace the existing display JSON files. It creates a parallel
Raw → Clean → Analysis → Display layer so the current site can keep working while
quality/analysis engines are introduced gradually.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
EVENTS = DATA / "events"
RAW = DATA / "raw"
CLEAN = DATA / "clean"
ANALYSIS = DATA / "analysis"
DISPLAY = DATA / "display"
ADMIN = DATA / "admin"

SPECIES_ORDER = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG", "OTHER"]
SPECIES_LABEL = {
    "BEEF": "한우",
    "PORK": "돈육",
    "POULTRY": "계육",
    "DUCK": "오리",
    "EGG": "계란",
    "OTHER": "기타",
}

OFFICIAL_HINTS = re.compile(r"농림축산식품부|KAHIS|축산물품질평가원|KREI|OASIS|정부|농식품부", re.I)
PUBLIC_HINTS = re.compile(r"자조금|협회|농협|지자체|도청|시청|군청|위원회", re.I)
COMPANY_HINTS = re.compile(r"프로모션|신제품|출시|브랜드|기업|업체|매장|쿠폰|할인", re.I)
DISEASE_HINTS = re.compile(r"ASF|아프리카돼지열병|구제역|조류인플루엔자|고병원성|AI|방역|살처분|농장", re.I)
PRICE_HINTS = re.compile(r"가격|시세|지육|산지|소비자가|급등|하락|상승|할인", re.I)
SUPPLY_HINTS = re.compile(r"도축|도계|출하|수급|공급|사육|입식|산란계", re.I)
POLICY_HINTS = re.compile(r"정책|대책|지원|고시|점검|수입|관세|가격안정|비축", re.I)
DEMAND_HINTS = re.compile(r"수요|행사|명절|추석|설|복날|외식|소비|학교급식", re.I)


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


def stable_id(*parts: str) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def normalize_text(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s or "").strip().lower())
    s = re.sub(r"\s+-\s+[^-]{1,30}$", "", s)
    return s


def source_domain(item: dict) -> str:
    url = item.get("source_url") or item.get("url") or ""
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def source_level(item: dict) -> tuple[int, str]:
    title = " ".join(str(item.get(k, "")) for k in ["publisher", "source_title", "title"])
    category = item.get("category", "")
    if category == "OFFICIAL" or OFFICIAL_HINTS.search(title):
        return 5, "정부/공식기관"
    if PUBLIC_HINTS.search(title):
        return 4, "공공/협회"
    if COMPANY_HINTS.search(title):
        return 2, "기업/보도자료"
    if item.get("publisher") or source_domain(item):
        return 3, "언론/검색뉴스"
    return 1, "기타/불명"


def freshness_score(item: dict) -> int:
    dt = item.get("published_at") or item.get("date") or ""
    try:
        if dt.endswith("Z"):
            d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        elif len(dt) == 10:
            d = datetime.fromisoformat(dt + "T00:00:00+00:00")
        else:
            d = datetime.fromisoformat(dt)
        age_days = max(0, (datetime.now(timezone.utc) - d.astimezone(timezone.utc)).days)
    except Exception:
        return 40
    if age_days <= 1:
        return 100
    if age_days <= 3:
        return 88
    if age_days <= 7:
        return 74
    if age_days <= 14:
        return 55
    if age_days <= 30:
        return 35
    return 15


def evidence_type(title: str, tags: list[str], doc_type: str) -> str:
    text = " ".join([title, doc_type, " ".join(tags or [])])
    if DISEASE_HINTS.search(text):
        return "질병/방역"
    if SUPPLY_HINTS.search(text):
        return "수급/도축"
    if PRICE_HINTS.search(text):
        return "가격"
    if POLICY_HINTS.search(text):
        return "정책/고시"
    if DEMAND_HINTS.search(text):
        return "수요/행사"
    return "일반"


def market_direction(title: str, evidence: str) -> tuple[str, int, str]:
    text = title or ""
    up = re.search(r"급등|상승|강세|부족|감소|발생|확산|방역|살처분|수급난|가격\s*인상", text)
    down = re.search(r"하락|약세|안정|할인|공급\s*확대|수입\s*증가|가격\s*인하", text)
    if up and not down:
        return "up", 4 if evidence in {"질병/방역", "수급/도축", "가격"} else 3, "상방 요인"
    if down and not up:
        return "down", 4 if evidence in {"가격", "정책/고시"} else 3, "하방 요인"
    if evidence in {"질병/방역", "수급/도축"}:
        return "up", 3, "상방 가능성"
    return "neutral", 2, "중립/보조"


def quality_score(level: int, fresh: int, duplicate: bool, species: list[str], filtered: bool) -> int:
    score = level * 12 + int(fresh * 0.35)
    if species:
        score += 10
    if duplicate:
        score -= 25
    if filtered:
        score -= 30
    return max(0, min(100, score))


def build_raw() -> list[dict]:
    news = read_json(EVENTS / "events_news.json", {"items": []}).get("items", [])
    official = read_json(EVENTS / "events_official.json", {"items": []}).get("items", [])
    raw_items = []
    for source_name, items in [("events_news", news), ("events_official", official)]:
        for item in items:
            item = dict(item)
            item["layer_id"] = stable_id(source_name, item.get("event_id"), item.get("title"), item.get("url") or item.get("source_url"))
            item["raw_source_file"] = source_name + ".json"
            item["ingested_at"] = now_iso()
            raw_items.append(item)
    return raw_items


def build_clean(raw_items: list[dict]) -> tuple[list[dict], list[dict]]:
    title_groups = defaultdict(list)
    for item in raw_items:
        key = normalize_text(item.get("title", ""))[:90]
        title_groups[key].append(item["layer_id"])

    clean = []
    rejected = []
    for item in raw_items:
        title = item.get("title", "")
        tags = item.get("tags") or []
        species = item.get("species") or []
        doc_type = item.get("doc_type", "")
        key = normalize_text(title)[:90]
        duplicate_group_id = stable_id(key)
        is_duplicate = len(title_groups[key]) > 1 and title_groups[key][0] != item["layer_id"]
        level, level_label = source_level(item)
        fresh = freshness_score(item)
        evidence = evidence_type(title, tags, doc_type)
        direction, impact, direction_label = market_direction(title, evidence)
        filtered = bool(item.get("filter_reason")) or not species
        q = quality_score(level, fresh, is_duplicate, species, filtered)
        enriched = dict(item)
        enriched.update({
            "duplicate_group_id": duplicate_group_id,
            "is_duplicate": is_duplicate,
            "source_domain": source_domain(item),
            "source_level": level,
            "source_level_label": level_label,
            "freshness_score": fresh,
            "evidence_type": evidence,
            "market_direction": direction,
            "market_direction_label": direction_label,
            "impact_score": impact,
            "quality_score": q,
            "quality_policy": "phase1_quality_v1"
        })
        if q < 25:
            enriched["reject_reason"] = "quality_score_low"
            rejected.append(enriched)
        else:
            clean.append(enriched)
    return clean, rejected


def build_analysis(clean_items: list[dict]) -> tuple[dict, dict, dict]:
    species_stats = {sp: {"items": 0, "quality_sum": 0, "impact_sum": 0, "up": 0, "down": 0, "neutral": 0, "official": 0, "coverage": set()} for sp in SPECIES_ORDER}
    for item in clean_items:
        for sp in item.get("species") or []:
            if sp not in species_stats:
                continue
            st = species_stats[sp]
            st["items"] += 1
            st["quality_sum"] += item.get("quality_score", 0)
            st["impact_sum"] += item.get("impact_score", 0)
            st[item.get("market_direction", "neutral")] += 1
            if item.get("source_level", 0) >= 5:
                st["official"] += 1
            st["coverage"].add(item.get("evidence_type", "일반"))

    score_items = []
    chains = []
    for sp, st in species_stats.items():
        if st["items"] == 0:
            signal_score = 0
            quality_avg = 0
            direction = "hold"
            coverage_rate = 0
            status = "판단 유보"
        else:
            quality_avg = round(st["quality_sum"] / st["items"])
            coverage_rate = round(min(100, len(st["coverage"]) / 5 * 100))
            directional = st["up"] - st["down"]
            signal_score = max(0, min(100, 50 + directional * 6 + st["impact_sum"] + (st["official"] * 4)))
            if coverage_rate < 40 or quality_avg < 45:
                direction = "hold"
                status = "판단 유보"
            elif signal_score >= 70:
                direction = "up"
                status = "상방"
            elif signal_score <= 35:
                direction = "down"
                status = "하방"
            else:
                direction = "neutral"
                status = "보합/혼조"
        score_items.append({
            "id": sp,
            "name": SPECIES_LABEL.get(sp, sp),
            "signal_score": signal_score,
            "direction": direction,
            "status": status,
            "quality_score": quality_avg,
            "coverage_rate": coverage_rate,
            "evidence_count": st["items"],
            "official_count": st["official"],
            "direction_counts": {"up": st["up"], "down": st["down"], "neutral": st["neutral"]},
            "coverage_types": sorted(st["coverage"]),
            "score_policy": "phase1_evidence_score_draft"
        })
        chains.append({
            "id": sp,
            "name": SPECIES_LABEL.get(sp, sp),
            "chain": [
                {"step": "자료수집", "value": f"{st['items']}건", "meaning": "축종 관련 자료 수"},
                {"step": "품질평가", "value": f"{quality_avg}점", "meaning": "출처·최신성·중복 여부 기반"},
                {"step": "커버리지", "value": f"{coverage_rate}%", "meaning": "가격·수급·질병·정책·수요 근거 범위"},
                {"step": "시장신호", "value": f"{signal_score}점", "meaning": status}
            ]
        })

    matrix = {
        "updated_at": now_iso(),
        "policy": "phase1_static_cross_market_draft",
        "items": [
            {"from": "POULTRY", "to": "PORK", "effect": "+", "strength": 0.3, "memo": "계육 강세 시 돈육 일부 대체수요 가능"},
            {"from": "PORK", "to": "POULTRY", "effect": "+", "strength": 0.2, "memo": "돈육 강세 시 계육 대체수요 가능"},
            {"from": "EGG", "to": "POULTRY", "effect": "risk", "strength": 0.2, "memo": "AI 이슈는 계란·계육 공통 리스크"},
            {"from": "DUCK", "to": "POULTRY", "effect": "risk", "strength": 0.2, "memo": "가금 질병 이슈는 닭·오리 공통 리스크"}
        ]
    }
    return {"updated_at": now_iso(), "species": score_items}, {"updated_at": now_iso(), "items": chains}, matrix


def build_admin_log(raw_items: list[dict], clean_items: list[dict], rejected: list[dict]) -> dict:
    by_species = Counter()
    by_evidence = Counter()
    for item in clean_items:
        by_evidence[item.get("evidence_type", "일반")] += 1
        for sp in item.get("species") or []:
            by_species[sp] += 1
    return {
        "updated_at": now_iso(),
        "policy": "phase1_admin_log_v1",
        "summary": {
            "raw_count": len(raw_items),
            "clean_count": len(clean_items),
            "rejected_count": len(rejected),
            "duplicate_count": sum(1 for x in clean_items if x.get("is_duplicate")),
            "official_count": sum(1 for x in clean_items if x.get("source_level", 0) >= 5),
            "average_quality": round(sum(x.get("quality_score", 0) for x in clean_items) / max(1, len(clean_items)))
        },
        "by_species": dict(by_species),
        "by_evidence_type": dict(by_evidence),
        "recent_rejections": rejected[:20]
    }


def build_display_summary(scores: dict) -> dict:
    return {
        "updated_at": now_iso(),
        "notice": "Phase 1 병렬 Display Layer 초안입니다. 기존 화면용 market_dashboard.json은 아직 대체하지 않습니다.",
        "species": scores.get("species", [])
    }


def main() -> int:
    raw_items = build_raw()
    clean_items, rejected = build_clean(raw_items)
    scores, chains, matrix = build_analysis(clean_items)
    admin_log = build_admin_log(raw_items, clean_items, rejected)

    write_json(RAW / "events_raw.json", {"updated_at": now_iso(), "items": raw_items})
    write_json(CLEAN / "events_clean.json", {"updated_at": now_iso(), "items": clean_items})
    write_json(CLEAN / "events_rejected.json", {"updated_at": now_iso(), "items": rejected})
    write_json(ANALYSIS / "evidence_scores.json", scores)
    write_json(ANALYSIS / "evidence_chains.json", chains)
    write_json(ANALYSIS / "cross_market_matrix.json", matrix)
    write_json(DISPLAY / "market_dashboard_phase1.json", build_display_summary(scores))
    write_json(ADMIN / "quality_report.json", admin_log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

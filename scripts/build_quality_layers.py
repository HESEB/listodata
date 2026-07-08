#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build robust data quality layers and Evidence Score outputs.

This script is intentionally defensive because it runs inside GitHub Actions.
It reads collected news/official events and writes Raw → Clean → Analysis → Display layers.
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
SPECIES_LABEL = {"BEEF": "한우", "PORK": "돈육", "POULTRY": "계육", "DUCK": "오리", "EGG": "계란", "OTHER": "기타"}

SCORE_AXES = {
    "price": {"label": "가격", "max": 30, "types": ["가격"]},
    "supply": {"label": "수급/도축", "max": 25, "types": ["수급/도축"]},
    "disease": {"label": "질병/방역", "max": 20, "types": ["질병/방역"]},
    "policy": {"label": "정책/고시", "max": 10, "types": ["정책/고시"]},
    "news": {"label": "뉴스/수요", "max": 15, "types": ["수요/행사", "일반"]},
}
EVIDENCE_TO_AXIS = {etype: axis for axis, cfg in SCORE_AXES.items() for etype in cfg["types"]}

OFFICIAL_HINTS = re.compile(r"농림축산식품부|KAHIS|축산물품질평가원|KREI|OASIS|정부|농식품부", re.I)
PUBLIC_HINTS = re.compile(r"자조금|협회|농협|지자체|도청|시청|군청|위원회", re.I)
COMPANY_HINTS = re.compile(r"프로모션|신제품|출시|브랜드|기업|업체|매장|쿠폰|할인", re.I)
DISEASE_HINTS = re.compile(r"ASF|아프리카돼지열병|구제역|조류인플루엔자|고병원성|\bAI\b|방역|살처분|농장", re.I)
PRICE_HINTS = re.compile(r"가격|시세|지육|산지|소비자가|급등|하락|상승|할인|인상|인하", re.I)
SUPPLY_HINTS = re.compile(r"도축|도계|출하|수급|공급|사육|입식|산란계|물량|재고", re.I)
POLICY_HINTS = re.compile(r"정책|대책|지원|고시|점검|수입|관세|가격안정|비축|할당관세", re.I)
DEMAND_HINTS = re.compile(r"수요|행사|명절|추석|설|복날|외식|소비|학교급식|프로모션", re.I)
UP_HINTS = re.compile(r"급등|상승|강세|부족|감소|발생|확산|방역|살처분|수급난|가격\s*인상|긴급|이동제한", re.I)
DOWN_HINTS = re.compile(r"하락|약세|안정|할인|공급\s*확대|수입\s*증가|가격\s*인하|완화", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, set):
        return sorted(json_safe(v) for v in value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = json_safe(payload)
    path.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_id(*parts: str) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def normalize_text(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s or "").strip().lower())
    s = re.sub(r"\s+-\s+[^-]{1,30}$", "", s)
    return s


def source_url(item: dict) -> str:
    return item.get("source_url") or item.get("url") or ""


def source_domain(item: dict) -> str:
    try:
        return urlparse(source_url(item)).netloc.replace("www.", "")
    except Exception:
        return ""


def source_level(item: dict) -> tuple[int, str]:
    text = " ".join(str(item.get(k, "")) for k in ["publisher", "source_title", "title"])
    if item.get("category") == "OFFICIAL" or OFFICIAL_HINTS.search(text):
        return 5, "정부/공식기관"
    if PUBLIC_HINTS.search(text):
        return 4, "공공/협회"
    if COMPANY_HINTS.search(text):
        return 2, "기업/보도자료"
    if item.get("publisher") or source_domain(item):
        return 3, "언론/검색뉴스"
    return 1, "기타/불명"


def freshness_score(item: dict) -> int:
    raw = item.get("published_at") or item.get("date") or ""
    try:
        if raw.endswith("Z"):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        elif len(raw) == 10:
            dt = datetime.fromisoformat(raw + "T00:00:00+00:00")
        else:
            dt = datetime.fromisoformat(raw)
        age = max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days)
    except Exception:
        return 40
    if age <= 1:
        return 100
    if age <= 3:
        return 88
    if age <= 7:
        return 74
    if age <= 14:
        return 55
    if age <= 30:
        return 35
    return 15


def evidence_type(title: str, tags: list[str], doc_type: str) -> str:
    text = " ".join([title or "", doc_type or "", " ".join(tags or [])])
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
    up = UP_HINTS.search(title or "")
    down = DOWN_HINTS.search(title or "")
    if up and not down:
        return "up", 5 if evidence in ["질병/방역", "수급/도축"] else 4, "상방 요인"
    if down and not up:
        return "down", 4 if evidence in ["가격", "정책/고시"] else 3, "하방 요인"
    if evidence in ["질병/방역", "수급/도축"]:
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


def item_strength(item: dict) -> float:
    quality = (item.get("quality_score", 0) or 0) / 100
    fresh = (item.get("freshness_score", 0) or 0) / 100
    src = min(1, (item.get("source_level", 1) or 1) / 5)
    impact = min(1, (item.get("impact_score", 1) or 1) / 5)
    return max(0.05, min(1, quality * 0.35 + fresh * 0.20 + src * 0.25 + impact * 0.20))


def build_raw() -> list[dict]:
    news = read_json(EVENTS / "events_news.json", {"items": []}).get("items", [])
    official = read_json(EVENTS / "events_official.json", {"items": []}).get("items", [])
    out = []
    for source_name, items in [("events_news", news), ("events_official", official)]:
        for item in items:
            row = dict(item)
            row["layer_id"] = stable_id(source_name, row.get("event_id"), row.get("title"), source_url(row))
            row["raw_source_file"] = source_name + ".json"
            row["ingested_at"] = now_iso()
            out.append(row)
    return out


def build_clean(raw_items: list[dict]) -> tuple[list[dict], list[dict]]:
    groups = defaultdict(list)
    for item in raw_items:
        groups[normalize_text(item.get("title", ""))[:90]].append(item["layer_id"])
    clean, rejected = [], []
    for item in raw_items:
        title = item.get("title", "")
        species = item.get("species") or []
        tags = item.get("tags") or []
        doc_type = item.get("doc_type", "")
        key = normalize_text(title)[:90]
        duplicate = len(groups[key]) > 1 and groups[key][0] != item["layer_id"]
        level, level_label = source_level(item)
        fresh = freshness_score(item)
        evidence = evidence_type(title, tags, doc_type)
        direction, impact, direction_label = market_direction(title, evidence)
        filtered = bool(item.get("filter_reason")) or not species
        q = quality_score(level, fresh, duplicate, species, filtered)
        axis = EVIDENCE_TO_AXIS.get(evidence, "news")
        row = dict(item)
        row.update({
            "duplicate_group_id": stable_id(key),
            "is_duplicate": duplicate,
            "source_domain": source_domain(item),
            "source_level": level,
            "source_level_label": level_label,
            "freshness_score": fresh,
            "evidence_type": evidence,
            "evidence_axis": axis,
            "market_direction": direction,
            "market_direction_label": direction_label,
            "impact_score": impact,
            "quality_score": q,
            "quality_policy": "phase2_quality_v3_sanitized",
        })
        if q < 25:
            row["reject_reason"] = "quality_score_low"
            rejected.append(row)
        else:
            clean.append(row)
    return clean, rejected


def init_stats() -> dict:
    return {
        sp: {
            "items": 0,
            "quality_sum": 0,
            "up": 0,
            "down": 0,
            "neutral": 0,
            "hold": 0,
            "official": 0,
            "coverage": set(),
            "axis": {axis: {"items": 0, "quality_sum": 0, "source_sum": 0, "impact_sum": 0.0, "up": 0, "down": 0, "neutral": 0, "examples": []} for axis in SCORE_AXES},
        }
        for sp in SPECIES_ORDER
    }


def axis_score(axis_data: dict, axis_key: str) -> int:
    max_score = SCORE_AXES[axis_key]["max"]
    if axis_data["items"] <= 0:
        return 0
    avg_strength = axis_data["impact_sum"] / max(1, axis_data["items"])
    volume_factor = min(1, axis_data["items"] / 4)
    balance = axis_data.get("up", 0) - axis_data.get("down", 0)
    direction_factor = 1.0 if balance > 0 else (0.45 if balance < 0 else 0.70)
    official_bonus = min(1.15, 1 + axis_data["source_sum"] / max(1, axis_data["items"]) * 0.03)
    raw = max_score * (avg_strength * 0.65 + volume_factor * 0.35) * direction_factor * official_bonus
    return max(0, min(max_score, round(raw)))


def status_from_score(score: int, confidence: int, coverage: int, official: int, count: int) -> tuple[str, str]:
    if count == 0 or coverage < 35 or confidence < 40:
        return "hold", "판단 유보"
    if official == 0 and confidence < 55:
        return "hold", "보조자료 수준"
    if score >= 75:
        return "up", "상방 우세"
    if score >= 60:
        return "up", "상방 가능성"
    if score <= 35:
        return "down", "하방 가능성"
    return "neutral", "보합/혼조"


def reason_from_breakdown(breakdown: dict, counts: dict) -> str:
    top = sorted(breakdown.items(), key=lambda kv: kv[1], reverse=True)[:3]
    parts = [f"{SCORE_AXES[k]['label']} {v}점" for k, v in top if v > 0]
    if not parts:
        return "유효 근거 부족"
    if counts.get("up", 0) > counts.get("down", 0):
        tail = "상방성 자료가 우세"
    elif counts.get("down", 0) > counts.get("up", 0):
        tail = "하방성 자료가 우세"
    else:
        tail = "상·하방 자료가 혼재"
    return " + ".join(parts) + f" 기반, {tail}"


def serializable_axes() -> dict:
    return {k: {"label": v["label"], "max": v["max"], "types": list(v["types"])} for k, v in SCORE_AXES.items()}


def build_analysis(clean_items: list[dict]) -> tuple[dict, dict, dict]:
    stats = init_stats()
    for item in clean_items:
        axis = item.get("evidence_axis") or EVIDENCE_TO_AXIS.get(item.get("evidence_type"), "news")
        if axis not in SCORE_AXES:
            axis = "news"
        direction = item.get("market_direction") or "neutral"
        if direction not in ["up", "down", "neutral", "hold"]:
            direction = "neutral"
        strength = item_strength(item)
        for sp in item.get("species") or []:
            if sp not in stats:
                continue
            st = stats[sp]
            ad = st["axis"][axis]
            st["items"] += 1
            st["quality_sum"] += item.get("quality_score", 0)
            st[direction] += 1
            if item.get("source_level", 0) >= 5:
                st["official"] += 1
            st["coverage"].add(item.get("evidence_type", "일반"))
            ad["items"] += 1
            ad["quality_sum"] += item.get("quality_score", 0)
            ad["source_sum"] += item.get("source_level", 0)
            ad["impact_sum"] += strength
            ad[direction] += 1
            if len(ad["examples"]) < 3:
                ad["examples"].append({"title": item.get("title", ""), "direction": direction, "source_level": item.get("source_level", 0), "quality_score": item.get("quality_score", 0)})

    score_items, chain_items = [], []
    for sp, st in stats.items():
        if st["items"]:
            quality_avg = round(st["quality_sum"] / st["items"])
            coverage_rate = round(min(100, len(st["coverage"]) / 5 * 100))
            breakdown = {axis: axis_score(st["axis"][axis], axis) for axis in SCORE_AXES}
            signal_score = max(0, min(100, sum(breakdown.values())))
            confidence = round(min(100, quality_avg * 0.45 + coverage_rate * 0.35 + min(100, st["official"] * 15) * 0.20))
            direction, status = status_from_score(signal_score, confidence, coverage_rate, st["official"], st["items"])
        else:
            quality_avg = coverage_rate = signal_score = confidence = 0
            breakdown = {axis: 0 for axis in SCORE_AXES}
            direction, status = "hold", "판단 유보"
        counts = {"up": st["up"], "down": st["down"], "neutral": st["neutral"], "hold": st["hold"]}
        axis_detail = {}
        for axis in SCORE_AXES:
            ad = st["axis"][axis]
            axis_detail[axis] = {
                "label": SCORE_AXES[axis]["label"],
                "max_score": SCORE_AXES[axis]["max"],
                "score": breakdown[axis],
                "items": ad["items"],
                "up": ad["up"],
                "down": ad["down"],
                "neutral": ad["neutral"],
                "examples": ad["examples"],
            }
        reason = reason_from_breakdown(breakdown, counts)
        score_items.append({
            "id": sp,
            "name": SPECIES_LABEL.get(sp, sp),
            "signal_score": signal_score,
            "direction": direction,
            "status": status,
            "quality_score": quality_avg,
            "confidence_score": confidence,
            "coverage_rate": coverage_rate,
            "evidence_count": st["items"],
            "official_count": st["official"],
            "direction_counts": counts,
            "coverage_types": sorted(st["coverage"]),
            "score_breakdown": breakdown,
            "score_breakdown_labels": {k: SCORE_AXES[k]["label"] for k in SCORE_AXES},
            "axis_detail": axis_detail,
            "reason": reason,
            "score_policy": "phase2_evidence_score_v3_sanitized",
        })
        chain_items.append({
            "id": sp,
            "name": SPECIES_LABEL.get(sp, sp),
            "chain": [
                {"step": "자료수집", "value": f"{st['items']}건", "meaning": "축종 관련 자료 수"},
                {"step": "품질평가", "value": f"{quality_avg}점", "meaning": "출처·최신성·중복 여부 기반"},
                {"step": "커버리지", "value": f"{coverage_rate}%", "meaning": "가격·수급·질병·정책·수요 근거 범위"},
                {"step": "점수구성", "value": ", ".join([f"{SCORE_AXES[k]['label']} {v}" for k, v in breakdown.items()]), "meaning": "Evidence Score Breakdown"},
                {"step": "시장신호", "value": f"{signal_score}점", "meaning": status},
            ],
            "score_breakdown": breakdown,
            "confidence_score": confidence,
            "reason": reason,
        })
    matrix = {
        "updated_at": now_iso(),
        "policy": "phase1_static_cross_market_draft",
        "items": [
            {"from": "POULTRY", "to": "PORK", "effect": "+", "strength": 0.3, "memo": "계육 강세 시 돈육 일부 대체수요 가능"},
            {"from": "PORK", "to": "POULTRY", "effect": "+", "strength": 0.2, "memo": "돈육 강세 시 계육 대체수요 가능"},
            {"from": "EGG", "to": "POULTRY", "effect": "risk", "strength": 0.2, "memo": "AI 이슈는 계란·계육 공통 리스크"},
            {"from": "DUCK", "to": "POULTRY", "effect": "risk", "strength": 0.2, "memo": "가금 질병 이슈는 닭·오리 공통 리스크"},
        ],
    }
    return {"updated_at": now_iso(), "policy": "phase2_evidence_score_v3_sanitized", "score_axes": serializable_axes(), "species": score_items}, {"updated_at": now_iso(), "policy": "phase2_evidence_chain_v3_sanitized", "items": chain_items}, matrix


def build_admin_log(raw_items: list[dict], clean_items: list[dict], rejected: list[dict]) -> dict:
    by_species = Counter()
    by_evidence = Counter()
    by_axis = Counter()
    for item in clean_items:
        by_evidence[item.get("evidence_type", "일반")] += 1
        by_axis[item.get("evidence_axis", "news")] += 1
        for sp in item.get("species") or []:
            by_species[sp] += 1
    return {
        "updated_at": now_iso(),
        "policy": "phase2_admin_log_v3_sanitized",
        "summary": {
            "raw_count": len(raw_items),
            "clean_count": len(clean_items),
            "rejected_count": len(rejected),
            "duplicate_count": sum(1 for x in clean_items if x.get("is_duplicate")),
            "official_count": sum(1 for x in clean_items if x.get("source_level", 0) >= 5),
            "average_quality": round(sum(x.get("quality_score", 0) for x in clean_items) / max(1, len(clean_items))),
        },
        "by_species": dict(by_species),
        "by_evidence_type": dict(by_evidence),
        "by_evidence_axis": dict(by_axis),
        "recent_rejections": rejected[:20],
    }


def build_display_summary(scores: dict) -> dict:
    return {"updated_at": now_iso(), "notice": "Phase 2 Display Layer 초안입니다. 기존 market_dashboard.json은 별도로 유지됩니다.", "species": scores.get("species", [])}


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
    print(f"quality layers: raw={len(raw_items)} clean={len(clean_items)} rejected={len(rejected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

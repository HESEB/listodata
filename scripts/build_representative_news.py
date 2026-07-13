#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Context Filter v2 and representative livestock news.

Official numeric data remains the primary decision source. News is filtered and
ranked only as explanatory evidence for the DSS 2.0 dashboard.

Phase 8-6 adds a hard publication-date cutoff. Articles outside the configured
window, with missing/invalid dates, or with implausible future dates cannot be
selected as representative news. They remain available to other history/market
memory layers.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY_PATH = DATA / "design" / "representative_news_policy.json"
CLEAN_PATH = DATA / "clean" / "events_clean.json"
DIRECTION_PATH = DATA / "analysis" / "direction_engine_v2.json"
REP_ADMIN = DATA / "admin" / "representative_news.json"
REP_ANALYSIS = DATA / "analysis" / "representative_news.json"
CTX_ADMIN = DATA / "admin" / "context_filter_v2.json"
CTX_ANALYSIS = DATA / "analysis" / "context_filter_v2.json"
SPECIES = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG"]


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None


def normalize(text: str) -> str:
    text = re.sub(r"\s+-\s+[^-]{2,40}$", "", str(text or "")).lower()
    return re.sub(r"[^0-9a-z가-힣]+", "", text)[:180]


def contains(text: str, words: list[str]) -> list[str]:
    low = text.lower()
    return [w for w in words if w and w.lower() in low]


def combined_text(item: dict) -> str:
    fields = [item.get("title"), item.get("summary"), item.get("description"), item.get("body"), item.get("publisher"), item.get("source_title")]
    fields += item.get("tags", []) if isinstance(item.get("tags"), list) else []
    return " ".join(str(x or "") for x in fields)


def direction_map(doc: dict) -> dict[str, dict]:
    rows = doc.get("species", []) if isinstance(doc, dict) else []
    if isinstance(rows, dict):
        return rows
    return {str(x.get("species")): x for x in rows if isinstance(x, dict) and x.get("species")}


def context_evaluate(item: dict, policy: dict) -> dict:
    text = combined_text(item)
    rules = policy.get("context_rules", {})
    livestock = contains(text, rules.get("livestock_positive", []))
    ai_tech = contains(text, rules.get("ai_tech_negative", []))
    duck_idiom = contains(text, rules.get("duck_idiom_negative", []))
    duck_positive = contains(text, rules.get("duck_positive", []))
    avian_positive = contains(text, rules.get("avian_positive", []))
    species = list(item.get("species") or [])

    score = 35
    reasons = []
    score += min(40, len(livestock) * 8)
    if livestock:
        reasons.append("축산 문맥 확인")
    if ai_tech:
        score -= 70
        reasons.append("인공지능/기술 문맥")
    if duck_idiom and not duck_positive:
        score -= 70
        reasons.append("오리 관용표현")
    if re.search(r"\bAI\b", text, re.I) and not avian_positive:
        score -= 45
        reasons.append("AI 조류질병 문맥 없음")
    if "DUCK" in species and not duck_positive and not avian_positive:
        score -= 35
        reasons.append("오리 축종 주변 문맥 부족")
    if any(x in species for x in ["POULTRY", "DUCK", "EGG"]) and re.search(r"\bAI\b", text, re.I) and avian_positive:
        score += 20
        reasons.append("조류질병 문맥 확인")
    if item.get("category") == "OFFICIAL":
        score += 10
    score = max(0, min(100, score))
    accepted = score >= float(policy.get("minimum_context_score", 55))
    return {
        "event_id": item.get("event_id"),
        "title": item.get("title"),
        "species": species,
        "context_score": round(score, 1),
        "accepted": accepted,
        "reason": "; ".join(reasons) or "축산 문맥 근거 부족",
        "hits": {"livestock": livestock[:8], "ai_tech": ai_tech[:5], "duck_idiom": duck_idiom[:5], "duck_positive": duck_positive[:5], "avian_positive": avian_positive[:5]},
    }


def publication_eligibility(item: dict, policy: dict, reference_time: datetime) -> dict:
    eligibility = policy.get("representative_eligibility", {})
    cutoff_days = int(eligibility.get("hard_cutoff_days") or policy.get("windows_days", {}).get("decision_evidence", 30))
    future_limit = float(eligibility.get("exclude_future_days_over", 1))
    raw_date = item.get("published_at") or item.get("date")
    reasons = eligibility.get("reason_codes", {})

    if not raw_date:
        return {
            "eligible": not bool(eligibility.get("exclude_missing_published_at", True)),
            "reason_code": "missing_date",
            "reason": reasons.get("missing_date", "게시일 없음"),
            "published_at": None,
            "age_days": None,
            "cutoff_days": cutoff_days,
        }

    published = parse_dt(raw_date)
    if not published:
        return {
            "eligible": False,
            "reason_code": "invalid_date",
            "reason": reasons.get("invalid_date", "게시일 형식 오류"),
            "published_at": raw_date,
            "age_days": None,
            "cutoff_days": cutoff_days,
        }

    age_days = (reference_time - published).total_seconds() / 86400
    if age_days < -future_limit:
        return {
            "eligible": False,
            "reason_code": "future_date",
            "reason": reasons.get("future_date", "미래 게시일 오류"),
            "published_at": raw_date,
            "age_days": round(age_days, 1),
            "cutoff_days": cutoff_days,
        }
    if age_days > cutoff_days:
        return {
            "eligible": False,
            "reason_code": "older_than_cutoff",
            "reason": reasons.get("older_than_cutoff", f"게시일 {cutoff_days}일 초과"),
            "published_at": raw_date,
            "age_days": round(age_days, 1),
            "cutoff_days": cutoff_days,
        }
    return {
        "eligible": True,
        "reason_code": "within_cutoff",
        "reason": f"게시일 {cutoff_days}일 이내",
        "published_at": raw_date,
        "age_days": round(max(0, age_days), 1),
        "cutoff_days": cutoff_days,
    }


def freshness_score(item: dict, window: int, reference_time: datetime) -> float:
    dt = parse_dt(item.get("published_at") or item.get("date"))
    if not dt:
        return 0
    age = max(0, (reference_time - dt).total_seconds() / 86400)
    return round(max(0, 100 * (1 - age / max(window, 1))), 1)


def alignment_score(item: dict, direction: dict) -> float:
    if direction.get("decision_status") != "ready":
        return 50
    news_dir = str(item.get("market_direction") or "neutral")
    d = str(direction.get("direction_code") or "hold")
    if news_dir == "neutral":
        return 55
    if news_dir == "up" and d in {"up", "strong_up"}:
        return 100
    if news_dir == "down" and d in {"down", "strong_down"}:
        return 100
    return 15


def relevance_score(item: dict, species: str) -> float:
    assigned = item.get("species") or []
    if species not in assigned:
        return 0
    return 100 if len(assigned) == 1 else max(55, 100 - (len(assigned) - 1) * 15)


def representative_score(item: dict, species: str, direction: dict, policy: dict, reference_time: datetime) -> dict:
    weights = policy.get("representative_weights", {})
    freshness = freshness_score(item, int(policy.get("windows_days", {}).get("decision_evidence", 30)), reference_time)
    impact = min(100, max(0, float(item.get("impact_score") or 0) * 20))
    level = str(item.get("source_level") or 1)
    source = float(policy.get("source_level_scores", {}).get(level, 30))
    relevance = relevance_score(item, species)
    alignment = alignment_score(item, direction)
    score = (
        freshness * float(weights.get("freshness", 30))
        + impact * float(weights.get("impact", 25))
        + source * float(weights.get("source_reliability", 20))
        + relevance * float(weights.get("species_relevance", 15))
        + alignment * float(weights.get("official_direction_alignment", 10))
    ) / 100
    return {"score": round(score, 1), "breakdown": {"freshness": freshness, "impact": impact, "source_reliability": source, "species_relevance": relevance, "official_direction_alignment": alignment}}


def main() -> int:
    policy = read_json(POLICY_PATH, {})
    clean = read_json(CLEAN_PATH, {"items": []})
    items = [x for x in clean.get("items", []) if isinstance(x, dict)]
    directions = direction_map(read_json(DIRECTION_PATH, {"species": []}))
    reference_time = now()

    accepted = []
    rejected = []
    for item in items:
        result = context_evaluate(item, policy)
        (accepted if result["accepted"] else rejected).append({"item": item, "context": result})

    context_payload = {
        "updated_at": reference_time.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "policy": "phase7_context_filter_v2_v1",
        "summary": {"input_count": len(items), "accepted_count": len(accepted), "rejected_count": len(rejected), "acceptance_rate": round(len(accepted) / max(len(items), 1) * 100, 1)},
        "accepted_preview": [x["context"] for x in accepted[:30]],
        "rejected": [x["context"] for x in rejected[:100]],
    }

    result_species = []
    limit = int(policy.get("dashboard_limit_per_species", 2))
    min_score = float(policy.get("minimum_representative_score", 45))
    cutoff_excluded_by_event: dict[str, dict] = {}

    for sp in SPECIES:
        candidates = []
        seen = set()
        species_cutoff_excluded = 0
        for row in accepted:
            item = row["item"]
            if sp not in (item.get("species") or []):
                continue
            key = normalize(item.get("title") or "") or item.get("event_id")
            if key in seen:
                continue
            seen.add(key)

            eligibility = publication_eligibility(item, policy, reference_time)
            if not eligibility["eligible"]:
                species_cutoff_excluded += 1
                event_key = str(item.get("event_id") or key or hashlib.sha1(str(item).encode()).hexdigest()[:12])
                if event_key not in cutoff_excluded_by_event:
                    cutoff_excluded_by_event[event_key] = {
                        "event_id": item.get("event_id"),
                        "title": item.get("title"),
                        "publisher": item.get("publisher") or item.get("source_title"),
                        "published_at": item.get("published_at") or item.get("date"),
                        "species": list(item.get("species") or []),
                        "reason_code": eligibility["reason_code"],
                        "reason": eligibility["reason"],
                        "age_days": eligibility["age_days"],
                        "cutoff_days": eligibility["cutoff_days"],
                        "destination": policy.get("representative_eligibility", {}).get("stale_destination", "market_memory"),
                    }
                continue

            rank = representative_score(item, sp, directions.get(sp, {}), policy, reference_time)
            if rank["score"] < min_score:
                continue
            candidates.append({
                "event_id": item.get("event_id"),
                "title": item.get("title"),
                "publisher": item.get("publisher") or item.get("source_title"),
                "url": item.get("url") or item.get("source_url"),
                "published_at": item.get("published_at") or item.get("date"),
                "age_days": eligibility["age_days"],
                "market_direction": item.get("market_direction"),
                "impact_score": item.get("impact_score"),
                "quality_score": item.get("quality_score"),
                "source_level": item.get("source_level"),
                "context_score": row["context"]["context_score"],
                "representative_score": rank["score"],
                "score_breakdown": rank["breakdown"],
                "selection_id": hashlib.sha1(f"{sp}:{item.get('event_id')}".encode()).hexdigest()[:12],
            })
        candidates.sort(key=lambda x: (x["representative_score"], x.get("published_at") or ""), reverse=True)
        result_species.append({
            "species": sp,
            "direction": directions.get(sp, {}).get("direction_code", "hold"),
            "candidate_count": len(candidates),
            "cutoff_excluded_count": species_cutoff_excluded,
            "representatives": candidates[:limit],
            "more": candidates[limit:],
        })

    cutoff_excluded = sorted(
        cutoff_excluded_by_event.values(),
        key=lambda x: (x.get("age_days") is None, -(x.get("age_days") or 0)),
    )
    cutoff_reason_counts: dict[str, int] = {}
    for row in cutoff_excluded:
        code = str(row.get("reason_code") or "unknown")
        cutoff_reason_counts[code] = cutoff_reason_counts.get(code, 0) + 1

    representative_payload = {
        "updated_at": reference_time.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "policy": "phase8_representative_news_v2",
        "summary": {
            "species_count": len(result_species),
            "representative_count": sum(len(x["representatives"]) for x in result_species),
            "accepted_context_count": len(accepted),
            "rejected_context_count": len(rejected),
            "hard_cutoff_days": int(policy.get("representative_eligibility", {}).get("hard_cutoff_days", 30)),
            "cutoff_excluded_count": len(cutoff_excluded),
            "cutoff_reason_counts": cutoff_reason_counts,
        },
        "species": result_species,
        "cutoff_excluded": cutoff_excluded[:200],
        "notice": policy.get("notice"),
    }
    for path in [CTX_ADMIN, CTX_ANALYSIS]:
        write_json(path, context_payload)
    for path in [REP_ADMIN, REP_ANALYSIS]:
        write_json(path, representative_payload)
    print(json.dumps({"context": context_payload["summary"], "representative": representative_payload["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

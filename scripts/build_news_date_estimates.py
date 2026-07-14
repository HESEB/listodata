#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estimate publication dates for representative-news review assistance.

The estimator never auto-approves a date. It enriches the existing administrator
review queue with candidates, evidence, confidence and original-source checks.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY_PATH = DATA / "design" / "news_date_estimation_policy.json"
CLEAN_PATH = DATA / "clean" / "events_clean.json"
REVIEW_ADMIN = DATA / "admin" / "representative_news_date_review.json"
REVIEW_ANALYSIS = DATA / "analysis" / "representative_news_date_review.json"
STATUS_ADMIN = DATA / "admin" / "news_date_estimation.json"
STATUS_ANALYSIS = DATA / "analysis" / "news_date_estimation.json"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now(value: datetime | None = None) -> str:
    dt = value or now()
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    candidates = [text]
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 8:
        candidates.append(f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}")
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def stable_key(item: dict) -> str:
    return str(item.get("event_id") or item.get("event_key") or item.get("url") or item.get("source_url") or item.get("title") or "")


def add_candidate(rows: list[dict], value: Any, source: str, label: str, confidence: int, evidence: str) -> None:
    dt = parse_date(value)
    if not dt:
        return
    iso = iso_now(dt)
    if any(row.get("estimated_published_at") == iso and row.get("source") == source for row in rows):
        return
    rows.append({
        "estimated_published_at": iso,
        "source": source,
        "source_label": label,
        "confidence": confidence,
        "evidence": evidence,
    })


def metadata_candidates(item: dict, policy: dict) -> list[dict]:
    rows: list[dict] = []
    configured = next((x for x in policy.get("candidate_sources", []) if x.get("source") == "metadata"), {})
    fields = configured.get("fields", [])
    confidence = int(configured.get("confidence", 95))
    label = configured.get("label", "기사 메타데이터")
    containers = [item]
    for key in ("metadata", "source", "raw", "original"):
        if isinstance(item.get(key), dict):
            containers.append(item[key])
    for container in containers:
        for field in fields:
            if container.get(field) not in (None, ""):
                add_candidate(rows, container.get(field), "metadata", label, confidence, f"{field}={container.get(field)}")
    return rows


def url_candidates(item: dict, policy: dict) -> list[dict]:
    rows: list[dict] = []
    configured = next((x for x in policy.get("candidate_sources", []) if x.get("source") == "url_path"), {})
    confidence = int(configured.get("confidence", 82))
    label = configured.get("label", "원문 URL 날짜")
    url = str(item.get("url") or item.get("source_url") or "")
    if not url:
        return rows
    text = unquote(urlparse(url).path + "?" + urlparse(url).query)
    patterns = [
        r"(?<!\d)(20\d{2})[/-](0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])(?!\d)",
        r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            year, month, day = match.groups()
            value = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
            add_candidate(rows, value, "url_path", label, confidence, match.group(0))
    return rows


def text_candidates(item: dict, policy: dict) -> list[dict]:
    rows: list[dict] = []
    configured = next((x for x in policy.get("candidate_sources", []) if x.get("source") == "text"), {})
    confidence = int(configured.get("confidence", 68))
    label = configured.get("label", "제목·요약 날짜 표현")
    for field in configured.get("fields", ["title", "summary", "description"]):
        text = str(item.get(field) or "")
        for match in re.finditer(r"(?<!\d)(20\d{2})[.\-/년\s]+(0?[1-9]|1[0-2])[.\-/월\s]+(0?[1-9]|[12]\d|3[01])(?:일)?(?!\d)", text):
            year, month, day = match.groups()
            value = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
            add_candidate(rows, value, "text", label, confidence, f"{field}: {match.group(0)}")
    return rows


def collection_candidates(item: dict, policy: dict) -> list[dict]:
    rows: list[dict] = []
    configured = next((x for x in policy.get("candidate_sources", []) if x.get("source") == "collection_time"), {})
    confidence = int(configured.get("confidence", 35))
    label = configured.get("label", "수집·최초 발견 시각")
    for field in configured.get("fields", []):
        if item.get(field) not in (None, ""):
            add_candidate(rows, item.get(field), "collection_time", label, confidence, f"{field}={item.get(field)}")
    return rows


def confidence_level(score: int, policy: dict) -> str:
    levels = policy.get("confidence_levels", {})
    if score >= int(levels.get("high", 85)):
        return "high"
    if score >= int(levels.get("medium", 65)):
        return "medium"
    return "low"


def main() -> int:
    policy = read_json(POLICY_PATH, {})
    review = read_json(REVIEW_ADMIN, {"queue": [], "summary": {}})
    clean = read_json(CLEAN_PATH, {"items": []})
    reference = now()
    future_tolerance = float(policy.get("future_tolerance_days", 1))
    max_age = float(policy.get("maximum_candidate_age_days", 3650))

    item_index: dict[str, dict] = {}
    for item in clean.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        for key in {stable_key(item), str(item.get("event_id") or ""), str(item.get("url") or item.get("source_url") or "")}:
            if key:
                item_index[key] = item

    enriched = []
    source_counts: dict[str, int] = {}
    high_count = medium_count = low_count = no_candidate_count = 0
    for queued in review.get("queue", []) or []:
        if not isinstance(queued, dict):
            continue
        original = item_index.get(str(queued.get("event_id") or "")) or item_index.get(str(queued.get("event_key") or "")) or item_index.get(str(queued.get("url") or "")) or queued
        candidates = metadata_candidates(original, policy) + url_candidates(original, policy) + text_candidates(original, policy) + collection_candidates(original, policy)
        valid = []
        for candidate in candidates:
            dt = parse_date(candidate.get("estimated_published_at"))
            if not dt:
                continue
            age = (reference - dt).total_seconds() / 86400
            if age < -future_tolerance or age > max_age:
                candidate["validity"] = "out_of_range"
                candidate["age_days"] = round(age, 1)
                continue
            candidate["validity"] = "candidate"
            candidate["age_days"] = round(max(0, age), 1)
            valid.append(candidate)
        valid.sort(key=lambda x: (int(x.get("confidence", 0)), x.get("estimated_published_at", "")), reverse=True)
        best = valid[0] if valid else None
        for candidate in valid:
            source = str(candidate.get("source") or "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
        level = confidence_level(int((best or {}).get("confidence", 0)), policy) if best else "none"
        if level == "high":
            high_count += 1
        elif level == "medium":
            medium_count += 1
        elif level == "low":
            low_count += 1
        else:
            no_candidate_count += 1
        enriched.append({
            **queued,
            "date_estimation": {
                "status": "candidate_found" if best else "no_candidate",
                "best_candidate": best,
                "confidence_level": level,
                "candidate_count": len(valid),
                "candidates": valid[:10],
                "auto_apply": False,
                "original_url_available": bool(queued.get("url") or original.get("url") or original.get("source_url")),
                "verification_required": True,
            },
        })

    summary = dict(review.get("summary") or {})
    summary.update({
        "estimated_queue_count": len(enriched),
        "candidate_found_count": len(enriched) - no_candidate_count,
        "high_confidence_count": high_count,
        "medium_confidence_count": medium_count,
        "low_confidence_count": low_count,
        "no_candidate_count": no_candidate_count,
        "auto_applied_count": 0,
    })
    review["updated_at"] = iso_now(reference)
    review["policy"] = "phase8_representative_news_date_review_v2"
    review["summary"] = summary
    review["queue"] = enriched
    review["date_estimation_notice"] = policy.get("notice")

    status = {
        "updated_at": iso_now(reference),
        "policy": policy.get("policy", "phase8_news_date_estimation_v1"),
        "summary": {
            "review_queue_count": len(enriched),
            "candidate_found_count": len(enriched) - no_candidate_count,
            "high_confidence_count": high_count,
            "medium_confidence_count": medium_count,
            "low_confidence_count": low_count,
            "no_candidate_count": no_candidate_count,
            "auto_applied_count": 0,
            "source_counts": source_counts,
        },
        "notice": policy.get("notice"),
    }
    for path in (REVIEW_ADMIN, REVIEW_ANALYSIS):
        write_json(path, review)
    for path in (STATUS_ADMIN, STATUS_ANALYSIS):
        write_json(path, status)
    print(json.dumps(status["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

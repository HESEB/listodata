#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge original-page date metadata into the administrator date review queue."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CLEAN = DATA / "clean" / "events_clean.json"
REVIEW_PATHS = [DATA / "admin" / "representative_news_date_review.json", DATA / "analysis" / "representative_news_date_review.json"]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def keys(item: dict) -> set[str]:
    return {str(item.get("event_id") or ""), str(item.get("url") or item.get("source_url") or ""), str(item.get("event_key") or "")}


def main() -> int:
    clean = read_json(CLEAN, {"items": []})
    index: dict[str, dict] = {}
    for item in clean.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        for key in keys(item):
            if key:
                index[key] = item

    merged_total = 0
    for path in REVIEW_PATHS:
        review = read_json(path, {"queue": [], "summary": {}})
        for row in review.get("queue", []) or []:
            if not isinstance(row, dict):
                continue
            original = None
            for key in keys(row):
                if key and key in index:
                    original = index[key]
                    break
            metadata = (original or {}).get("original_date_metadata") or {}
            source_candidates = metadata.get("candidates") or []
            if not source_candidates:
                continue
            estimation = row.setdefault("date_estimation", {})
            existing = estimation.get("candidates") or []
            seen = {(x.get("estimated_published_at"), x.get("source"), x.get("field")) for x in existing if isinstance(x, dict)}
            added = 0
            for candidate in source_candidates:
                if not isinstance(candidate, dict) or not candidate.get("published_at"):
                    continue
                converted = {
                    "estimated_published_at": candidate.get("published_at"),
                    "source": "original_" + str(candidate.get("source") or "metadata"),
                    "source_label": "원문 " + str(candidate.get("source") or "메타데이터"),
                    "confidence": int(candidate.get("confidence") or 95),
                    "evidence": f"{candidate.get('field')}: {candidate.get('raw_value')}",
                    "validity": "candidate",
                    "field": candidate.get("field"),
                }
                signature = (converted["estimated_published_at"], converted["source"], converted.get("field"))
                if signature in seen:
                    continue
                existing.append(converted)
                seen.add(signature)
                added += 1
            if added:
                existing.sort(key=lambda x: (int(x.get("confidence", 0)), x.get("estimated_published_at", "")), reverse=True)
                estimation["candidates"] = existing[:15]
                estimation["candidate_count"] = len(estimation["candidates"])
                estimation["best_candidate"] = estimation["candidates"][0]
                estimation["status"] = "candidate_found"
                estimation["confidence_level"] = "high" if int(estimation["best_candidate"].get("confidence", 0)) >= 85 else "medium"
                estimation["original_page_checked"] = True
                estimation["original_page_status"] = metadata.get("status")
                estimation["original_final_url"] = metadata.get("final_url")
                merged_total += added
        summary = review.setdefault("summary", {})
        summary["original_metadata_candidate_count"] = merged_total
        review["original_metadata_notice"] = "JSON-LD·OpenGraph·meta·time 태그 후보는 자동 확정하지 않으며 관리자 승인이 필요합니다."
        write_json(path, review)
    print(json.dumps({"merged_candidate_count": merged_total}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a review-only queue for high-priority KOSIS candidates.

This script never approves candidates and never changes mapping files. It combines
candidate quality output with existing administrator decisions so the static review
screen can preserve prior work while presenting P1 candidates first.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
QUALITY = DATA / "admin" / "kosis_candidate_quality.json"
APPROVALS = DATA / "admin" / "kosis_detail_approvals.json"
POLICY = DATA / "config" / "kosis_p1_batch_review_policy.json"
ADMIN_OUT = DATA / "admin" / "kosis_p1_batch_review.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_p1_batch_review.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def key(row: dict) -> str:
    return "|".join(str(row.get(name) or "") for name in ("metric_id", "org_id", "tbl_id", "ITM_ID", "C1_ID"))


def main() -> int:
    generated_at = now_iso()
    quality = read_json(QUALITY, {"summary": {}, "candidates": []})
    approvals = read_json(APPROVALS, {"approvals": []})
    policy = read_json(POLICY, {})
    existing = {key(row): row for row in approvals.get("approvals", []) or [] if isinstance(row, dict)}
    selection = policy.get("selection") or {}
    max_rows = int(selection.get("maximum_rows", 30))

    candidates = [row for row in quality.get("candidates", []) or [] if isinstance(row, dict) and row.get("priority") == "P1"]
    candidates.sort(key=lambda row: (-int(row.get("quality_score") or 0), str(row.get("metric_id") or "")))
    queue = []
    for row in candidates[:max_rows]:
        prior = existing.get(key(row))
        queue.append({
            **row,
            "existing_decision": (prior or {}).get("decision"),
            "existing_reviewer": (prior or {}).get("reviewer"),
            "existing_note": (prior or {}).get("note"),
            "review_state": "already_reviewed" if prior and prior.get("decision") else "pending",
        })

    pending = sum(1 for row in queue if row["review_state"] == "pending")
    status = "p1_review_ready" if pending else ("review_complete" if queue else "candidate_generation_required")
    summary = {
        "status": status,
        "p1_candidate_count": len(candidates),
        "queue_count": len(queue),
        "pending_count": pending,
        "already_reviewed_count": len(queue) - pending,
        "recommended_count": sum(1 for row in queue if row.get("recommended_for_review")),
        "auto_approved_count": 0,
        "auto_applied_count": 0,
    }
    payload = {
        "updated_at": generated_at,
        "policy": "phase10_kosis_p1_batch_review_v1",
        "summary": summary,
        "queue": queue,
        "approval_registry_path": str(APPROVALS.relative_to(ROOT)),
        "next_action": "P1 후보의 공식 근거를 확인하고 일괄 검수 화면에서 승인 JSON을 생성하세요." if queue else "KOSIS 후보를 생성하고 품질점수를 계산하세요.",
        "security": {"api_key_exposed": False, "request_url_exposed": False},
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

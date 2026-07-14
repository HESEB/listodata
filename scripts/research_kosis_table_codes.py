#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 9-1 KOSIS table-code research helper.

This script never guesses or auto-applies table codes. It reads the research target
registry and reports whether candidates have the evidence required for approval.
An optional KOSIS_CODE_RESEARCH_JSON environment variable may contain an official
API response exported by the operator; raw API keys are never written.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
TARGETS = DATA / "config" / "kosis_code_research_targets.json"
ADMIN = DATA / "admin" / "kosis_code_research.json"
ANALYSIS = DATA / "analysis" / "kosis_code_research.json"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    config = read_json(TARGETS, {"targets": [], "approval_rules": {}})
    required = list((config.get("approval_rules") or {}).get("required_evidence") or [])
    imported = []
    raw = os.environ.get("KOSIS_CODE_RESEARCH_JSON", "").strip()
    if raw:
        try:
            doc = json.loads(raw)
            imported = doc if isinstance(doc, list) else list(doc.get("candidates") or [])
        except Exception:
            imported = []

    rows = []
    approved = 0
    candidate_count = 0
    for target in config.get("targets", []) or []:
        candidates = list(target.get("candidate_tables") or [])
        for candidate in imported:
            if not isinstance(candidate, dict):
                continue
            text = " ".join(str(candidate.get(k) or "") for k in ("table_name", "tbl_nm", "title", "name"))
            if any(word in text for word in target.get("keywords", []) or []):
                candidates.append(candidate)
        checked = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            normalized = {
                "org_id": candidate.get("org_id") or candidate.get("ORG_ID"),
                "tbl_id": candidate.get("tbl_id") or candidate.get("TBL_ID"),
                "table_name": candidate.get("table_name") or candidate.get("TBL_NM") or candidate.get("tbl_nm"),
                "period": candidate.get("period") or candidate.get("PRD_SE"),
                "item_codes": candidate.get("item_codes") or candidate.get("items") or [],
                "classification_codes": candidate.get("classification_codes") or candidate.get("classifications") or [],
                "official_response_checked_at": candidate.get("official_response_checked_at") or candidate.get("checked_at"),
                "source": "KOSIS official API response"
            }
            missing = [field for field in required if normalized.get(field) in (None, "", [], {})]
            normalized["approval_status"] = "approved_candidate" if not missing else "evidence_required"
            normalized["missing_evidence"] = missing
            if not missing:
                approved += 1
            checked.append(normalized)
        candidate_count += len(checked)
        rows.append({
            "research_id": target.get("research_id"),
            "keywords": target.get("keywords"),
            "period_expected": target.get("period_expected"),
            "metrics": target.get("metrics"),
            "status": "candidate_ready" if any(x["approval_status"] == "approved_candidate" for x in checked) else "research_required",
            "candidates": checked
        })

    status = "candidate_ready" if approved else "research_required"
    payload = {
        "updated_at": now_iso(),
        "policy": "phase9_kosis_code_research_v1",
        "summary": {"status": status, "target_count": len(rows), "candidate_count": candidate_count, "approved_candidate_count": approved, "auto_applied_count": 0},
        "targets": rows,
        "required_evidence": required,
        "notice": "공식 KOSIS 응답 근거가 완성된 후보만 승인 가능하며, 매핑 템플릿에는 자동 반영하지 않습니다."
    }
    write_json(ADMIN, payload)
    write_json(ANALYSIS, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

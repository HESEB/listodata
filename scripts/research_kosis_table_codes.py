#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 9 KOSIS table-code research helper.

This script never guesses or auto-applies table codes. It combines manually
exported official responses with authenticated catalog candidates. A table-list
candidate still requires item/classification evidence before approval.
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
CATALOG = DATA / "analysis" / "kosis_catalog_research.json"
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


def catalog_candidates_by_target() -> dict[str, list[dict]]:
    doc = read_json(CATALOG, {"targets": []})
    result: dict[str, list[dict]] = {}
    for target in doc.get("targets", []) or []:
        if not isinstance(target, dict):
            continue
        result[str(target.get("research_id") or "")] = [row for row in target.get("candidates", []) or [] if isinstance(row, dict)]
    return result


def main() -> int:
    config = read_json(TARGETS, {"targets": [], "approval_rules": {}})
    catalog_index = catalog_candidates_by_target()
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
    table_candidate_count = 0
    for target in config.get("targets", []) or []:
        research_id = str(target.get("research_id") or "")
        candidates = list(target.get("candidate_tables") or []) + list(catalog_index.get(research_id) or [])
        for candidate in imported:
            if not isinstance(candidate, dict):
                continue
            text = " ".join(str(candidate.get(k) or "") for k in ("table_name", "tbl_nm", "title", "name"))
            if any(word in text for word in target.get("keywords", []) or []):
                candidates.append(candidate)
        checked = []
        seen: set[tuple[str, str]] = set()
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
                "keyword_score": candidate.get("keyword_score"),
                "keyword_hits": candidate.get("keyword_hits") or [],
                "source": candidate.get("source") or "KOSIS official API response",
            }
            signature = (str(normalized.get("org_id") or ""), str(normalized.get("tbl_id") or normalized.get("table_name") or ""))
            if signature in seen:
                continue
            seen.add(signature)
            missing = [field for field in required if normalized.get(field) in (None, "", [], {})]
            normalized["approval_status"] = "approved_candidate" if not missing else ("table_candidate" if normalized.get("org_id") and normalized.get("tbl_id") else "evidence_required")
            normalized["missing_evidence"] = missing
            if normalized["approval_status"] == "approved_candidate":
                approved += 1
            elif normalized["approval_status"] == "table_candidate":
                table_candidate_count += 1
            checked.append(normalized)
        candidate_count += len(checked)
        rows.append({
            "research_id": research_id,
            "keywords": target.get("keywords"),
            "period_expected": target.get("period_expected"),
            "metrics": target.get("metrics"),
            "status": "candidate_ready" if any(x["approval_status"] == "approved_candidate" for x in checked) else ("table_candidate_found" if any(x["approval_status"] == "table_candidate" for x in checked) else "research_required"),
            "candidates": checked,
        })

    status = "candidate_ready" if approved else ("table_candidate_found" if table_candidate_count else "research_required")
    payload = {
        "updated_at": now_iso(),
        "policy": "phase9_kosis_code_research_v2",
        "summary": {
            "status": status,
            "target_count": len(rows),
            "candidate_count": candidate_count,
            "table_candidate_count": table_candidate_count,
            "approved_candidate_count": approved,
            "auto_applied_count": 0,
        },
        "targets": rows,
        "required_evidence": required,
        "notice": "통계목록 API 후보는 org_id·tbl_id 조사에 사용합니다. 항목·분류 코드까지 공식 응답으로 확인된 후보만 최종 승인할 수 있으며 매핑 템플릿에는 자동 반영하지 않습니다.",
    }
    write_json(ADMIN, payload)
    write_json(ANALYSIS, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

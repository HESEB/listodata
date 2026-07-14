#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Combine KOSIS catalog and detail evidence for Phase 9 code research.

No candidate is auto-applied. A candidate becomes approval-ready only when table,
item, classification and official-response evidence are all present.
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
DETAIL = DATA / "analysis" / "kosis_detail_research.json"
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


def catalog_index() -> dict[str, list[dict]]:
    doc = read_json(CATALOG, {"targets": []})
    return {str(x.get("research_id") or ""): [r for r in x.get("candidates", []) or [] if isinstance(r, dict)] for x in doc.get("targets", []) or [] if isinstance(x, dict)}


def detail_index() -> dict[tuple[str, str, str], dict]:
    doc = read_json(DETAIL, {"targets": []})
    out: dict[tuple[str, str, str], dict] = {}
    for target in doc.get("targets", []) or []:
        if not isinstance(target, dict):
            continue
        rid = str(target.get("research_id") or "")
        for table in target.get("tables", []) or []:
            if isinstance(table, dict):
                out[(rid, str(table.get("org_id") or ""), str(table.get("tbl_id") or ""))] = table
    return out


def flatten_detail(table: dict) -> tuple[list[dict], list[dict], list[str]]:
    items: dict[str, dict] = {}
    classes: dict[str, dict] = {}
    units: list[str] = []
    for metric in table.get("metrics", []) or []:
        if not isinstance(metric, dict):
            continue
        for row in metric.get("candidates", []) or []:
            if not isinstance(row, dict):
                continue
            if row.get("ITM_ID"):
                items[str(row["ITM_ID"])] = {"ITM_ID": row.get("ITM_ID"), "ITM_NM": row.get("ITM_NM"), "metric_id": metric.get("metric_id")}
            if row.get("C1_ID"):
                classes[str(row["C1_ID"])] = {"C1_ID": row.get("C1_ID"), "C1_NM": row.get("C1_NM"), "metric_id": metric.get("metric_id")}
            if row.get("UNIT_NM") and str(row["UNIT_NM"]) not in units:
                units.append(str(row["UNIT_NM"]))
    return list(items.values()), list(classes.values()), units


def main() -> int:
    config = read_json(TARGETS, {"targets": [], "approval_rules": {}})
    catalogs = catalog_index()
    details = detail_index()
    required = list((config.get("approval_rules") or {}).get("required_evidence") or [])
    imported = []
    raw = os.environ.get("KOSIS_CODE_RESEARCH_JSON", "").strip()
    if raw:
        try:
            doc = json.loads(raw); imported = doc if isinstance(doc, list) else list(doc.get("candidates") or [])
        except Exception:
            imported = []

    rows = []
    approved = candidate_count = table_candidate_count = detail_candidate_count = 0
    for target in config.get("targets", []) or []:
        research_id = str(target.get("research_id") or "")
        candidates = list(target.get("candidate_tables") or []) + list(catalogs.get(research_id) or [])
        for candidate in imported:
            if isinstance(candidate, dict):
                text = " ".join(str(candidate.get(k) or "") for k in ("table_name", "tbl_nm", "title", "name"))
                if any(word in text for word in target.get("keywords", []) or []):
                    candidates.append(candidate)
        checked = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            org_id = candidate.get("org_id") or candidate.get("ORG_ID")
            tbl_id = candidate.get("tbl_id") or candidate.get("TBL_ID")
            detail = details.get((research_id, str(org_id or ""), str(tbl_id or "")), {})
            item_codes, classification_codes, units = flatten_detail(detail)
            normalized = {
                "org_id": org_id,
                "tbl_id": tbl_id,
                "table_name": candidate.get("table_name") or candidate.get("TBL_NM") or candidate.get("tbl_nm"),
                "period": candidate.get("period") or candidate.get("PRD_SE"),
                "item_codes": candidate.get("item_codes") or candidate.get("items") or item_codes,
                "classification_codes": candidate.get("classification_codes") or candidate.get("classifications") or classification_codes,
                "units": candidate.get("units") or units,
                "metric_detail": detail.get("metrics") or [],
                "official_response_checked_at": candidate.get("official_response_checked_at") or candidate.get("checked_at") or detail.get("official_response_checked_at"),
                "keyword_score": candidate.get("keyword_score"),
                "keyword_hits": candidate.get("keyword_hits") or [],
                "source": "KOSIS catalog + parameter official API" if detail else (candidate.get("source") or "KOSIS official API response"),
            }
            signature = (str(normalized.get("org_id") or ""), str(normalized.get("tbl_id") or normalized.get("table_name") or ""))
            if signature in seen:
                continue
            seen.add(signature)
            missing = [field for field in required if normalized.get(field) in (None, "", [], {})]
            normalized["approval_status"] = "approved_candidate" if not missing else ("detail_candidate" if item_codes or classification_codes else ("table_candidate" if org_id and tbl_id else "evidence_required"))
            normalized["missing_evidence"] = missing
            if normalized["approval_status"] == "approved_candidate": approved += 1
            elif normalized["approval_status"] == "detail_candidate": detail_candidate_count += 1
            elif normalized["approval_status"] == "table_candidate": table_candidate_count += 1
            checked.append(normalized)
        candidate_count += len(checked)
        status = "candidate_ready" if any(x["approval_status"] == "approved_candidate" for x in checked) else ("detail_candidate_found" if any(x["approval_status"] == "detail_candidate" for x in checked) else ("table_candidate_found" if any(x["approval_status"] == "table_candidate" for x in checked) else "research_required"))
        rows.append({"research_id": research_id, "keywords": target.get("keywords"), "period_expected": target.get("period_expected"), "metrics": target.get("metrics"), "status": status, "candidates": checked})

    status = "candidate_ready" if approved else ("detail_candidate_found" if detail_candidate_count else ("table_candidate_found" if table_candidate_count else "research_required"))
    payload = {
        "updated_at": now_iso(), "policy": "phase9_kosis_code_research_v3",
        "summary": {"status": status, "target_count": len(rows), "candidate_count": candidate_count, "table_candidate_count": table_candidate_count, "detail_candidate_count": detail_candidate_count, "approved_candidate_count": approved, "auto_applied_count": 0},
        "targets": rows, "required_evidence": required,
        "notice": "통계목록과 상세 항목·분류 공식 응답을 결합합니다. 필수 근거가 완성된 후보만 승인 가능하며 매핑 템플릿에는 자동 반영하지 않습니다."
    }
    write_json(ADMIN, payload); write_json(ANALYSIS, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())

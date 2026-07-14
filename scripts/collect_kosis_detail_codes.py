#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect KOSIS item/classification/unit candidates for discovered tables.

The API key is read only from KOSIS_API_KEY. Results are research evidence only;
this script never edits the production mapping template or prints credentials.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CONFIG = DATA / "config" / "kosis_detail_api_config.json"
CATALOG = DATA / "admin" / "kosis_catalog_research.json"
TARGETS = DATA / "config" / "kosis_code_research_targets.json"
ADMIN_OUT = DATA / "admin" / "kosis_detail_research.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_detail_research.json"
USER_AGENT = "HESEB-KOSIS-Detail-Research/1.0"


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


def rows_from_response(doc: Any) -> list[dict]:
    if isinstance(doc, list):
        return [x for x in doc if isinstance(x, dict)]
    if isinstance(doc, dict):
        for key in ("data", "result", "list", "items", "rows"):
            value = doc.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def pick(row: dict, aliases: list[str]) -> Any:
    for key in aliases:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def fetch_json(endpoint: str, params: dict[str, Any], timeout: int, max_bytes: int) -> Any:
    url = endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise RuntimeError("response_too_large")
    return json.loads(raw.decode("utf-8", errors="replace"))


def metric_keywords(target: dict, metric_id: str) -> list[str]:
    words = list(target.get("keywords") or [])
    mapping = {
        "BEEF": ["한육우", "한우", "소"], "PORK": ["돼지", "한돈"],
        "POULTRY": ["육계", "닭", "도계"], "EGG": ["산란계", "계란", "달걀"],
        "DUCK": ["오리"], "INVENTORY": ["사육", "마릿수"],
        "SLAUGHTER": ["도축", "도계"], "PRODUCTION": ["생산"]
    }
    upper = metric_id.upper()
    for token, values in mapping.items():
        if token in upper:
            words.extend(values)
    return list(dict.fromkeys(str(x) for x in words if x))


def score_text(text: str, words: list[str]) -> tuple[int, list[str]]:
    low = text.lower()
    hits = [w for w in words if w.lower() in low]
    return len(hits), hits


def main() -> int:
    cfg = read_json(CONFIG, {})
    catalog = read_json(CATALOG, {"targets": []})
    target_cfg = read_json(TARGETS, {"targets": []})
    target_index = {str(x.get("research_id")): x for x in target_cfg.get("targets", []) if isinstance(x, dict)}
    secret_name = str(cfg.get("secret_name") or "KOSIS_API_KEY")
    api_key = os.environ.get(secret_name, "").strip()
    checked_at = now_iso()

    if not api_key:
        payload = {
            "updated_at": checked_at, "policy": cfg.get("policy", "phase9_kosis_detail_api_v1"),
            "summary": {"status": "credential_required", "secret_configured": False, "table_candidate_count": 0, "request_count": 0, "detail_row_count": 0, "metric_candidate_count": 0, "approved_candidate_count": 0, "error_count": 0, "auto_applied_count": 0},
            "targets": [], "errors": [f"GitHub Actions Secret {secret_name} 미등록"],
            "security": {"api_key_exposed": False}, "notice": cfg.get("notice")
        }
        write_json(ADMIN_OUT, payload); write_json(ANALYSIS_OUT, payload)
        print(json.dumps(payload["summary"], ensure_ascii=False)); return 0

    aliases = cfg.get("parameter_aliases") or {}
    endpoint = str(cfg.get("parameter_endpoint") or "https://kosis.kr/openapi/statisticsParameterData.do")
    common = dict(cfg.get("common_query") or {})
    timeout = int(cfg.get("request_timeout_seconds", 15))
    max_bytes = int(cfg.get("max_response_bytes", 4_000_000))
    limit = int(cfg.get("candidate_limit_per_run", 20))
    minimum_score = int(cfg.get("minimum_metric_keyword_score", 1))

    table_candidates: list[tuple[str, dict]] = []
    seen: set[tuple[str, str]] = set()
    for target in catalog.get("targets", []) or []:
        rid = str(target.get("research_id") or "")
        for candidate in target.get("candidates", []) or []:
            if not isinstance(candidate, dict) or not candidate.get("org_id") or not candidate.get("tbl_id"):
                continue
            key = (str(candidate.get("org_id")), str(candidate.get("tbl_id")))
            if key in seen:
                continue
            seen.add(key); table_candidates.append((rid, candidate))
    table_candidates = table_candidates[:limit]

    request_count = detail_rows = metric_candidates = approved = 0
    errors: list[dict] = []
    outputs: dict[str, dict] = {}
    for rid, table in table_candidates:
        params = {**common, "apiKey": api_key, "orgId": table.get("org_id"), "tblId": table.get("tbl_id")}
        request_count += 1
        try:
            rows = rows_from_response(fetch_json(endpoint, params, timeout, max_bytes))
        except Exception as exc:
            errors.append({"research_id": rid, "org_id": table.get("org_id"), "tbl_id": table.get("tbl_id"), "error": type(exc).__name__})
            rows = []
        detail_rows += len(rows)
        normalized_rows = []
        for raw in rows:
            item_id = pick(raw, list(aliases.get("item_id") or []))
            item_name = pick(raw, list(aliases.get("item_name") or []))
            class_id = pick(raw, list(aliases.get("classification_id") or []))
            class_name = pick(raw, list(aliases.get("classification_name") or []))
            unit = pick(raw, list(aliases.get("unit") or []))
            if not any((item_id, item_name, class_id, class_name, unit)):
                continue
            normalized_rows.append({"ITM_ID": item_id, "ITM_NM": item_name, "C1_ID": class_id, "C1_NM": class_name, "UNIT_NM": unit})

        target = target_index.get(rid, {})
        metrics = []
        for metric_id in target.get("metrics", []) or []:
            words = metric_keywords(target, str(metric_id))
            ranked = []
            for row in normalized_rows:
                text = " ".join(str(row.get(k) or "") for k in ("ITM_NM", "C1_NM", "UNIT_NM"))
                score, hits = score_text(text, words)
                if score < minimum_score:
                    continue
                candidate = {**row, "keyword_score": score, "keyword_hits": hits,
                             "evidence_status": "complete" if row.get("ITM_ID") and row.get("C1_ID") else "partial"}
                ranked.append(candidate)
            ranked.sort(key=lambda x: (x.get("evidence_status") == "complete", x.get("keyword_score", 0)), reverse=True)
            ranked = ranked[:20]
            metric_candidates += len(ranked)
            if any(x.get("evidence_status") == "complete" for x in ranked):
                approved += 1
            metrics.append({"metric_id": metric_id, "keywords": words, "candidate_count": len(ranked), "status": "candidate_ready" if ranked else "no_match", "candidates": ranked})

        bucket = outputs.setdefault(rid, {"research_id": rid, "tables": []})
        bucket["tables"].append({
            "org_id": table.get("org_id"), "tbl_id": table.get("tbl_id"), "table_name": table.get("table_name"),
            "period": table.get("period"), "official_response_checked_at": checked_at,
            "detail_row_count": len(normalized_rows), "metrics": metrics,
            "approval_status": "detail_candidate" if normalized_rows else "detail_required"
        })

    result_targets = []
    for target in target_cfg.get("targets", []) or []:
        rid = str(target.get("research_id") or "")
        row = outputs.get(rid, {"research_id": rid, "tables": []})
        row["status"] = "candidate_found" if row["tables"] else "catalog_candidate_required"
        result_targets.append(row)

    status = "candidate_found" if metric_candidates else ("catalog_candidate_required" if not table_candidates else "api_limited")
    payload = {
        "updated_at": checked_at, "policy": cfg.get("policy", "phase9_kosis_detail_api_v1"),
        "summary": {"status": status, "secret_configured": True, "table_candidate_count": len(table_candidates), "request_count": request_count, "detail_row_count": detail_rows, "metric_candidate_count": metric_candidates, "approved_candidate_count": approved, "error_count": len(errors), "auto_applied_count": 0},
        "targets": result_targets, "errors": errors[:100],
        "security": {"api_key_exposed": False, "request_query_exposed": False}, "notice": cfg.get("notice")
    }
    write_json(ADMIN_OUT, payload); write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())

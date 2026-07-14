#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect KOSIS statistics-list candidates for Phase 9 research.

The API key is read only from KOSIS_API_KEY. It is never printed or written.
Missing credentials and individual API failures are represented as status data
and do not fail the whole market-data workflow.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CONFIG_PATH = DATA / "config" / "kosis_catalog_api_config.json"
TARGET_PATH = DATA / "config" / "kosis_code_research_targets.json"
ADMIN_OUT = DATA / "admin" / "kosis_catalog_research.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_catalog_research.json"
USER_AGENT = "HESEB-KOSIS-Catalog-Research/1.0"


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


def fetch_json(endpoint: str, params: dict[str, Any], timeout: int) -> Any:
    url = endpoint + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(4_000_000)
    return json.loads(raw.decode("utf-8", errors="replace"))


def rows_from_response(doc: Any) -> list[dict]:
    if isinstance(doc, list):
        return [row for row in doc if isinstance(row, dict)]
    if isinstance(doc, dict):
        for key in ("data", "result", "list", "items"):
            value = doc.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def pick(row: dict, *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def normalize(row: dict, checked_at: str, request_meta: dict) -> dict:
    return {
        "org_id": pick(row, "ORG_ID", "orgId", "org_id"),
        "tbl_id": pick(row, "TBL_ID", "tblId", "tbl_id"),
        "table_name": pick(row, "TBL_NM", "tblNm", "table_name", "LIST_NM", "listNm"),
        "period": pick(row, "PRD_SE", "prdSe", "period"),
        "list_id": pick(row, "LIST_ID", "listId", "list_id"),
        "parent_list_id": pick(row, "PARENT_LIST_ID", "parentListId", "parent_list_id"),
        "list_type": pick(row, "LIST_TYPE", "listType", "list_type"),
        "vw_cd": request_meta.get("vwCd"),
        "official_response_checked_at": checked_at,
        "source": "KOSIS statisticsList official API",
    }


def score_candidate(candidate: dict, keywords: list[str]) -> tuple[int, list[str]]:
    text = " ".join(str(candidate.get(key) or "") for key in ("table_name", "tbl_id", "org_id")).lower()
    hits = [word for word in keywords if str(word).lower() in text]
    return len(hits), hits


def main() -> int:
    config = read_json(CONFIG_PATH, {})
    targets = read_json(TARGET_PATH, {"targets": []})
    secret_name = str(config.get("secret_name") or "KOSIS_API_KEY")
    api_key = os.environ.get(secret_name, "").strip()
    checked_at = now_iso()

    if not api_key:
        payload = {
            "updated_at": checked_at,
            "policy": config.get("policy", "phase9_kosis_catalog_api_v1"),
            "summary": {"status": "credential_required", "secret_configured": False, "request_count": 0, "response_row_count": 0, "candidate_count": 0, "target_ready_count": 0},
            "targets": [],
            "errors": [f"GitHub Actions Secret {secret_name} 미등록"],
            "security": {"api_key_exposed": False},
            "notice": config.get("notice"),
        }
        write_json(ADMIN_OUT, payload)
        write_json(ANALYSIS_OUT, payload)
        print(json.dumps(payload["summary"], ensure_ascii=False))
        return 0

    endpoint = str(config.get("endpoint") or "https://kosis.kr/openapi/statisticsList.do")
    common = dict(config.get("common_query") or {})
    timeout = int(config.get("request_timeout_seconds", 15))
    max_depth = int(config.get("max_depth", 5))
    max_requests = int(config.get("max_requests_per_run", 80))
    min_score = int(config.get("minimum_keyword_score", 1))
    per_target = int(config.get("candidate_limit_per_target", 30))

    queue = deque()
    for root in config.get("root_requests", []) or []:
        if isinstance(root, dict):
            queue.append((dict(root), 0))
    visited: set[tuple[str, str]] = set()
    collected: list[dict] = []
    errors: list[dict] = []
    request_count = 0

    while queue and request_count < max_requests:
        request_meta, depth = queue.popleft()
        signature = (str(request_meta.get("vwCd") or ""), str(request_meta.get("parentListId") or ""))
        if signature in visited:
            continue
        visited.add(signature)
        params = {**common, **request_meta, "apiKey": api_key}
        request_count += 1
        try:
            rows = rows_from_response(fetch_json(endpoint, params, timeout))
        except Exception as exc:
            errors.append({"vwCd": signature[0], "parentListId": signature[1], "error": type(exc).__name__})
            continue
        for raw in rows:
            normalized = normalize(raw, checked_at, request_meta)
            collected.append(normalized)
            child_id = normalized.get("list_id")
            has_table = bool(normalized.get("tbl_id"))
            if depth < max_depth and child_id and not has_table:
                queue.append(({"vwCd": request_meta.get("vwCd"), "parentListId": child_id}, depth + 1))

    result_targets = []
    all_candidate_keys: set[tuple[str, str]] = set()
    target_ready_count = 0
    for target in targets.get("targets", []) or []:
        ranked = []
        for candidate in collected:
            score, hits = score_candidate(candidate, list(target.get("keywords") or []))
            if score < min_score:
                continue
            row = dict(candidate)
            row["keyword_score"] = score
            row["keyword_hits"] = hits
            row["period_match"] = not candidate.get("period") or candidate.get("period") == target.get("period_expected")
            row["approval_status"] = "table_candidate" if candidate.get("org_id") and candidate.get("tbl_id") and candidate.get("table_name") else "hierarchy_candidate"
            ranked.append(row)
        ranked.sort(key=lambda row: (row.get("keyword_score", 0), bool(row.get("period_match")), bool(row.get("tbl_id"))), reverse=True)
        ranked = ranked[:per_target]
        for row in ranked:
            all_candidate_keys.add((str(row.get("org_id") or ""), str(row.get("tbl_id") or row.get("list_id") or "")))
        if any(row.get("approval_status") == "table_candidate" for row in ranked):
            target_ready_count += 1
        result_targets.append({
            "research_id": target.get("research_id"),
            "period_expected": target.get("period_expected"),
            "keywords": target.get("keywords"),
            "metrics": target.get("metrics"),
            "candidate_count": len(ranked),
            "status": "candidate_found" if ranked else "no_match",
            "candidates": ranked,
        })

    status = "candidate_found" if all_candidate_keys else ("api_empty" if not errors else "api_limited")
    payload = {
        "updated_at": checked_at,
        "policy": config.get("policy", "phase9_kosis_catalog_api_v1"),
        "summary": {
            "status": status,
            "secret_configured": True,
            "request_count": request_count,
            "response_row_count": len(collected),
            "candidate_count": len(all_candidate_keys),
            "target_ready_count": target_ready_count,
            "error_count": len(errors),
            "auto_applied_count": 0,
        },
        "targets": result_targets,
        "errors": errors[:100],
        "security": {"api_key_exposed": False, "request_query_exposed": False},
        "notice": "통계목록 후보만 생성합니다. 기관·통계표·항목·분류 코드의 최종 승인은 통계자료 API 검증 후 수동으로 진행합니다.",
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

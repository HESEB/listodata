#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect KOSIS item/classification candidates using metadata + live data probes.

Phase 10.5:
- Discover item/classification metadata with statisticsData.do?method=getMeta&type=ITM.
- Normalize KOSIS metadata to the internal ITM_ID / C1_ID approval contract.
- Mark a pair complete only when statisticsParameterData.do returns a matching row.
- Never write credentials or generated request URLs.
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
USER_AGENT = "HESEB-KOSIS-Detail-Research/2.0"


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


def text(value: Any) -> str:
    return str(value or "").strip()


def metric_words(target: dict, metric_id: str) -> list[str]:
    words = list(target.get("keywords") or [])
    mapping = {
        "BEEF": ["한육우", "한우", "소"],
        "PORK": ["돼지", "한돈"],
        "POULTRY": ["육계", "닭", "도계"],
        "EGG": ["산란계", "계란", "달걀"],
        "DUCK": ["오리"],
        "INVENTORY": ["사육", "마릿수", "두수", "수수"],
        "SLAUGHTER": ["도축", "도계"],
        "PRODUCTION": ["생산"],
    }
    upper = metric_id.upper()
    for token, values in mapping.items():
        if token in upper:
            words.extend(values)
    return list(dict.fromkeys(text(x) for x in words if text(x)))


def species_words(metric_id: str) -> list[str]:
    upper = metric_id.upper()
    mapping = {
        "BEEF": ["한육우", "한우", "소"],
        "PORK": ["돼지", "한돈"],
        "POULTRY": ["육계", "닭"],
        "EGG": ["산란계", "계란", "달걀"],
        "DUCK": ["오리"],
    }
    for token, values in mapping.items():
        if token in upper:
            return values
    return []


def score_row(row: dict, words: list[str]) -> tuple[int, list[str]]:
    haystack = " ".join(
        text(row.get(k))
        for k in ("OBJ_NM", "ITM_NM", "UNIT_NM", "UP_ITM_ID")
    ).lower()
    hits = [word for word in words if word.lower() in haystack]
    return len(hits), hits


def normalize_metadata(raw: dict, aliases: dict) -> dict:
    return {
        "OBJ_ID": pick(raw, list(aliases.get("object_id") or [])),
        "OBJ_NM": pick(raw, list(aliases.get("object_name") or [])),
        "ITM_ID": pick(raw, list(aliases.get("item_id") or [])),
        "ITM_NM": pick(raw, list(aliases.get("item_name") or [])),
        "UP_ITM_ID": pick(raw, list(aliases.get("parent_item_id") or [])),
        "OBJ_ID_SN": pick(raw, list(aliases.get("object_sequence") or [])),
        "UNIT_NM": pick(raw, list(aliases.get("unit") or [])),
    }


def ranked(rows: list[dict], words: list[str], minimum_score: int, limit: int) -> list[dict]:
    out = []
    for row in rows:
        score, hits = score_row(row, words)
        if score < minimum_score:
            continue
        out.append({**row, "keyword_score": score, "keyword_hits": hits})
    out.sort(key=lambda x: (int(x.get("keyword_score") or 0), bool(x.get("UNIT_NM"))), reverse=True)
    return out[:limit]


def probe_pair(
    endpoint: str,
    common: dict,
    api_key: str,
    table: dict,
    period: str,
    item_id: str,
    class_id: str,
    response_aliases: dict,
    timeout: int,
    max_bytes: int,
) -> tuple[bool, list[dict], str | None]:
    if not period:
        return False, [], "period_required"
    params = {
        **common,
        "apiKey": api_key,
        "orgId": table.get("org_id"),
        "tblId": table.get("tbl_id"),
        "objL1": class_id,
        "itmId": item_id,
        "prdSe": period,
    }
    try:
        response_rows = rows_from_response(fetch_json(endpoint, params, timeout, max_bytes))
    except Exception as exc:
        return False, [], type(exc).__name__
    item_aliases = list(response_aliases.get("item_id") or [])
    class_aliases = list(response_aliases.get("classification_value") or [])
    matched = [
        row for row in response_rows
        if text(pick(row, item_aliases)) == item_id and text(pick(row, class_aliases)) == class_id
    ]
    return bool(matched), matched, None


def main() -> int:
    cfg = read_json(CONFIG, {})
    catalog = read_json(CATALOG, {"targets": []})
    target_cfg = read_json(TARGETS, {"targets": []})
    target_index = {text(x.get("research_id")): x for x in target_cfg.get("targets", []) if isinstance(x, dict)}
    secret_name = text(cfg.get("secret_name") or "KOSIS_API_KEY")
    api_key = os.environ.get(secret_name, "").strip()
    checked_at = now_iso()

    if not api_key:
        payload = {
            "updated_at": checked_at,
            "policy": cfg.get("policy", "phase10_5_kosis_detail_api_v2"),
            "summary": {
                "status": "credential_required",
                "secret_configured": False,
                "table_candidate_count": 0,
                "request_count": 0,
                "metadata_row_count": 0,
                "probe_row_count": 0,
                "detail_row_count": 0,
                "metric_candidate_count": 0,
                "approved_candidate_count": 0,
                "error_count": 0,
                "auto_applied_count": 0,
            },
            "targets": [],
            "errors": [f"GitHub Actions Secret {secret_name} 미등록"],
            "security": {"api_key_exposed": False, "request_query_exposed": False},
            "notice": cfg.get("notice"),
        }
        write_json(ADMIN_OUT, payload)
        write_json(ANALYSIS_OUT, payload)
        print(json.dumps(payload["summary"], ensure_ascii=False))
        return 0

    metadata_endpoint = text(cfg.get("metadata_endpoint") or "https://kosis.kr/openapi/statisticsData.do")
    parameter_endpoint = text(cfg.get("parameter_endpoint") or "https://kosis.kr/openapi/Param/statisticsParameterData.do")
    metadata_query = dict(cfg.get("metadata_query") or {"method": "getMeta", "type": "ITM", "format": "json"})
    probe_query = dict(cfg.get("probe_query") or {"method": "getList", "format": "json", "jsonVD": "Y", "newEstPrdCnt": "1"})
    aliases = cfg.get("metadata_aliases") or {}
    response_aliases = cfg.get("response_aliases") or {}
    timeout = int(cfg.get("request_timeout_seconds") or 15)
    max_bytes = int(cfg.get("max_response_bytes") or 4_000_000)
    limit = int(cfg.get("candidate_limit_per_run") or 20)
    minimum_score = int(cfg.get("minimum_metric_keyword_score") or 1)
    max_pairs = int(cfg.get("max_probe_pairs_per_metric") or 6)

    table_candidates: list[tuple[str, dict]] = []
    seen: set[tuple[str, str]] = set()
    for target in catalog.get("targets", []) or []:
        rid = text(target.get("research_id"))
        for candidate in target.get("candidates", []) or []:
            if not isinstance(candidate, dict) or not candidate.get("org_id") or not candidate.get("tbl_id"):
                continue
            key = (text(candidate.get("org_id")), text(candidate.get("tbl_id")))
            if key in seen:
                continue
            seen.add(key)
            table_candidates.append((rid, candidate))
    table_candidates = table_candidates[:limit]

    request_count = 0
    metadata_row_count = 0
    probe_row_count = 0
    metric_candidates = 0
    complete_metric_count = 0
    errors: list[dict] = []
    outputs: dict[str, dict] = {}

    for rid, table in table_candidates:
        request_count += 1
        params = {
            **metadata_query,
            "apiKey": api_key,
            "orgId": table.get("org_id"),
            "tblId": table.get("tbl_id"),
        }
        try:
            raw_meta = rows_from_response(fetch_json(metadata_endpoint, params, timeout, max_bytes))
        except Exception as exc:
            errors.append({
                "stage": "metadata",
                "research_id": rid,
                "org_id": table.get("org_id"),
                "tbl_id": table.get("tbl_id"),
                "error": type(exc).__name__,
            })
            raw_meta = []
        metadata_rows = [normalize_metadata(row, aliases) for row in raw_meta]
        metadata_rows = [row for row in metadata_rows if row.get("ITM_ID")]
        metadata_row_count += len(metadata_rows)

        item_pool = [row for row in metadata_rows if text(row.get("UNIT_NM"))]
        if not item_pool:
            item_pool = [row for row in metadata_rows if text(row.get("OBJ_ID")).upper() in {"ITM", "ITEM"}]
        if not item_pool:
            item_pool = metadata_rows[:]

        class_pool = [row for row in metadata_rows if not text(row.get("UNIT_NM"))]
        if not class_pool:
            class_pool = [
                row for row in metadata_rows
                if text(row.get("OBJ_ID")).upper() not in {"ITM", "ITEM"}
            ]

        target = target_index.get(rid, {})
        period = text(table.get("period") or target.get("period_expected"))
        metrics = []
        for metric_id_value in target.get("metrics", []) or []:
            metric_id = text(metric_id_value)
            item_ranked = ranked(item_pool, metric_words(target, metric_id), minimum_score, 6)
            class_ranked = ranked(class_pool, species_words(metric_id) or metric_words(target, metric_id), minimum_score, 10)

            pair_candidates = []
            pair_seen = set()
            for item in item_ranked:
                for cls in class_ranked:
                    item_id = text(item.get("ITM_ID"))
                    class_id = text(cls.get("ITM_ID"))
                    if not item_id or not class_id or item_id == class_id:
                        continue
                    pair_key = (item_id, class_id)
                    if pair_key in pair_seen:
                        continue
                    pair_seen.add(pair_key)
                    pair_candidates.append((
                        int(item.get("keyword_score") or 0) + int(cls.get("keyword_score") or 0),
                        item,
                        cls,
                    ))
            pair_candidates.sort(key=lambda x: x[0], reverse=True)
            pair_candidates = pair_candidates[:max_pairs]

            candidates = []
            metric_complete = False
            for combined_score, item, cls in pair_candidates:
                request_count += 1
                ok, probe_rows, probe_error = probe_pair(
                    parameter_endpoint,
                    probe_query,
                    api_key,
                    table,
                    period,
                    text(item.get("ITM_ID")),
                    text(cls.get("ITM_ID")),
                    response_aliases,
                    timeout,
                    max_bytes,
                )
                probe_row_count += len(probe_rows)
                observed_unit = ""
                observed_class_name = text(cls.get("ITM_NM"))
                if probe_rows:
                    observed_unit = text(pick(probe_rows[0], list(response_aliases.get("unit") or [])))
                    observed_class_name = text(
                        pick(probe_rows[0], list(response_aliases.get("classification_name") or []))
                        or observed_class_name
                    )
                candidate = {
                    "ITM_ID": text(item.get("ITM_ID")),
                    "ITM_NM": text(item.get("ITM_NM")),
                    "C1_ID": text(cls.get("ITM_ID")),
                    "C1_NM": observed_class_name,
                    "UNIT_NM": observed_unit or text(item.get("UNIT_NM")),
                    "keyword_score": combined_score,
                    "keyword_hits": list(dict.fromkeys((item.get("keyword_hits") or []) + (cls.get("keyword_hits") or []))),
                    "metadata_object_id": cls.get("OBJ_ID"),
                    "evidence_status": "complete" if ok else "partial",
                    "probe_error": probe_error,
                    "probe_row_count": len(probe_rows),
                }
                candidates.append(candidate)
                if ok:
                    metric_complete = True
            candidates.sort(
                key=lambda x: (x.get("evidence_status") == "complete", int(x.get("keyword_score") or 0)),
                reverse=True,
            )
            candidates = candidates[:20]
            metric_candidates += len(candidates)
            if metric_complete:
                complete_metric_count += 1
            metrics.append({
                "metric_id": metric_id,
                "candidate_count": len(candidates),
                "status": "candidate_ready" if metric_complete else ("probe_required" if candidates else "no_match"),
                "candidates": candidates,
            })

        bucket = outputs.setdefault(rid, {"research_id": rid, "tables": []})
        bucket["tables"].append({
            "org_id": table.get("org_id"),
            "tbl_id": table.get("tbl_id"),
            "table_name": table.get("table_name"),
            "period": period or None,
            "official_response_checked_at": checked_at,
            "metadata_row_count": len(metadata_rows),
            "metrics": metrics,
            "approval_status": "detail_candidate" if any(
                c.get("evidence_status") == "complete"
                for metric in metrics for c in metric.get("candidates", [])
            ) else "detail_required",
        })

    result_targets = []
    for target in target_cfg.get("targets", []) or []:
        rid = text(target.get("research_id"))
        row = outputs.get(rid, {"research_id": rid, "tables": []})
        has_complete = any(
            c.get("evidence_status") == "complete"
            for table in row.get("tables", [])
            for metric in table.get("metrics", [])
            for c in metric.get("candidates", [])
        )
        row["status"] = "candidate_found" if has_complete else ("metadata_found" if row.get("tables") else "catalog_candidate_required")
        result_targets.append(row)

    if complete_metric_count:
        status = "candidate_found"
    elif not table_candidates:
        status = "catalog_candidate_required"
    elif metadata_row_count:
        status = "probe_required"
    else:
        status = "api_limited" if errors else "metadata_empty"

    summary = {
        "status": status,
        "secret_configured": True,
        "table_candidate_count": len(table_candidates),
        "request_count": request_count,
        "metadata_row_count": metadata_row_count,
        "probe_row_count": probe_row_count,
        "detail_row_count": metadata_row_count + probe_row_count,
        "metric_candidate_count": metric_candidates,
        "approved_candidate_count": complete_metric_count,
        "error_count": len(errors),
        "auto_applied_count": 0,
    }
    payload = {
        "updated_at": checked_at,
        "policy": cfg.get("policy", "phase10_5_kosis_detail_api_v2"),
        "summary": summary,
        "targets": result_targets,
        "errors": errors[:100],
        "security": {"api_key_exposed": False, "request_query_exposed": False},
        "notice": cfg.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

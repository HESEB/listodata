#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve the KOSIS mapping used by runtime URL generation and collection.

Operational mapping is used only when it was explicitly promoted. Otherwise the
legacy template remains the safe fallback. API keys are accepted only in memory
and are never written by this module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
OPERATIONAL = DATA / "config" / "kosis_table_mapping_operational.json"
TEMPLATE = DATA / "config" / "kosis_table_mapping_template.json"
URL_POLICY = DATA / "config" / "kosis_url_generator_policy.json"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def operational_is_promoted(doc: dict) -> bool:
    return str(doc.get("promotion_status") or "").lower() == "promoted" and bool(doc.get("tables"))


def resolve_mapping() -> tuple[dict, dict]:
    operational = read_json(OPERATIONAL, {"tables": []})
    if operational_is_promoted(operational):
        return operational, {
            "mapping_source": "operational",
            "mapping_path": str(OPERATIONAL.relative_to(ROOT)),
            "promotion_status": "promoted",
            "fallback_used": False,
        }
    template = read_json(TEMPLATE, {"tables": []})
    return template, {
        "mapping_source": "template_fallback",
        "mapping_path": str(TEMPLATE.relative_to(ROOT)),
        "promotion_status": str(operational.get("promotion_status") or "not_promoted"),
        "fallback_used": True,
    }


def table_index(mapping: dict) -> dict[str, dict]:
    return {
        str(table.get("connection_id") or ""): table
        for table in mapping.get("tables", []) or []
        if isinstance(table, dict) and table.get("connection_id")
    }


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def table_errors(table: dict) -> list[str]:
    errors: list[str] = []
    for field in ("connection_id", "org_id", "tbl_id", "period", "start_prd_de", "end_prd_de"):
        if not str(table.get(field) or "").strip() or "REPLACE_" in str(table.get(field) or ""):
            errors.append(f"{field} 미설정")
    if not table.get("selected"):
        errors.append("selected=false")
    mappings = [x for x in table.get("metric_mappings", []) or [] if isinstance(x, dict) and x.get("enabled", True)]
    if not mappings:
        errors.append("활성 지표 매핑 없음")
    for mapping in mappings:
        metric_id = str(mapping.get("metric_id") or "미상")
        item_id = str((mapping.get("item_selector") or {}).get("ITM_ID") or "")
        class_id = str((mapping.get("classification_selectors") or {}).get("C1_ID") or "")
        if not item_id or "REPLACE_" in item_id:
            errors.append(f"{metric_id}: ITM_ID 미설정")
        if not class_id or "REPLACE_" in class_id:
            errors.append(f"{metric_id}: C1_ID 미설정")
    return list(dict.fromkeys(errors))


def build_kosis_url(table: dict, api_key: str) -> tuple[str | None, list[str]]:
    errors = table_errors(table)
    if not api_key:
        errors.append("KOSIS_API_KEY 미등록")
    if errors:
        return None, errors
    policy = read_json(URL_POLICY, {})
    names = policy.get("parameter_names") or {}
    query = dict(policy.get("static_parameters") or {})
    item_ids = unique([
        str((m.get("item_selector") or {}).get("ITM_ID") or "")
        for m in table.get("metric_mappings", []) or [] if m.get("enabled", True)
    ])
    class_ids = unique([
        str((m.get("classification_selectors") or {}).get("C1_ID") or "")
        for m in table.get("metric_mappings", []) or [] if m.get("enabled", True)
    ])
    joiner = str(policy.get("joiner") or ",")
    query.update({
        names.get("api_key", "apiKey"): api_key,
        names.get("org_id", "orgId"): table.get("org_id"),
        names.get("table_id", "tblId"): table.get("tbl_id"),
        names.get("period", "prdSe"): table.get("period"),
        names.get("start_period", "startPrdDe"): table.get("start_prd_de"),
        names.get("end_period", "endPrdDe"): table.get("end_prd_de"),
        names.get("item_ids", "itmId"): joiner.join(item_ids),
        names.get("class_level_1_ids", "objL1"): joiner.join(class_ids),
    })
    endpoint = str(policy.get("endpoint") or "https://kosis.kr/openapi/Param/statisticsParameterData.do")
    return endpoint + "?" + urlencode(query, safe=","), []

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build KOSIS API URL templates from the active mapping.

A promoted operational mapping is preferred. Until promotion, the legacy template
remains the safe fallback. Real API keys are never read or persisted here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from kosis_mapping_runtime import resolve_mapping

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY_PATH = DATA / "config" / "kosis_url_generator_policy.json"
ADMIN_OUT = DATA / "admin" / "kosis_api_url_generation.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_api_url_generation.json"


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


def has_placeholder(value: Any, placeholders: list[str]) -> bool:
    if isinstance(value, str):
        return not value.strip() or any(token in value for token in placeholders)
    if isinstance(value, dict):
        return any(has_placeholder(v, placeholders) for v in value.values())
    if isinstance(value, list):
        return any(has_placeholder(v, placeholders) for v in value)
    return value is None


def unique(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def masked_url(url: str, placeholder: str) -> str:
    return url.replace(placeholder, "***API_KEY***")


def build_table(table: dict, mapping_doc: dict, policy: dict) -> dict:
    placeholders = list((mapping_doc.get("instructions") or {}).get("placeholder_values") or ["REPLACE_"])
    params = policy.get("parameter_names") or {}
    errors: list[str] = []
    warnings: list[str] = []

    for field in policy.get("required_ready_fields", []):
        if has_placeholder(table.get(field), placeholders):
            errors.append(f"{field} 미설정")
    if not table.get("selected"):
        errors.append("통계표 선정 확인 미완료")
    if not table.get("secret_name"):
        errors.append("secret_name 누락")

    enabled_mappings = [x for x in table.get("metric_mappings", []) or [] if x.get("enabled", True)]
    item_ids: list[str] = []
    class_ids: list[str] = []
    metric_results: list[dict] = []

    for mapping in enabled_mappings:
        metric_errors: list[str] = []
        item_id = str((mapping.get("item_selector") or {}).get("ITM_ID") or "").strip()
        class_id = str((mapping.get("classification_selectors") or {}).get("C1_ID") or "").strip()
        if has_placeholder(item_id, placeholders) or "REPLACE_" in item_id:
            metric_errors.append("ITM_ID 미설정")
        if has_placeholder(class_id, placeholders) or "REPLACE_" in class_id:
            metric_errors.append("C1_ID 미설정")
        if not mapping.get("metric_id"):
            metric_errors.append("metric_id 누락")
        if not metric_errors:
            item_ids.append(item_id)
            class_ids.append(class_id)
        metric_results.append({
            "metric_id": mapping.get("metric_id"),
            "species": mapping.get("species"),
            "ready": not metric_errors,
            "errors": metric_errors,
            "item_id": item_id if not metric_errors else None,
            "class_id": class_id if not metric_errors else None,
        })

    if not enabled_mappings:
        errors.append("활성 지표 매핑 없음")
    if any(not x["ready"] for x in metric_results):
        errors.append("지표 코드 미완료")

    item_ids = unique(item_ids)
    class_ids = unique(class_ids)
    joiner = str(policy.get("joiner") or ",")
    api_key_placeholder = str(policy.get("api_key_placeholder") or "{API_KEY}")
    query = dict(policy.get("static_parameters") or {})
    query.update({
        params.get("api_key", "apiKey"): api_key_placeholder,
        params.get("org_id", "orgId"): table.get("org_id", ""),
        params.get("table_id", "tblId"): table.get("tbl_id", ""),
        params.get("period", "prdSe"): table.get("period", ""),
        params.get("start_period", "startPrdDe"): table.get("start_prd_de", ""),
        params.get("end_period", "endPrdDe"): table.get("end_prd_de", ""),
        params.get("item_ids", "itmId"): joiner.join(item_ids),
        params.get("class_level_1_ids", "objL1"): joiner.join(class_ids),
    })

    ready = not errors
    candidate_url = f"{policy.get('endpoint')}?{urlencode(query, safe='{},')}" if ready else None
    if ready and len(item_ids) != len(enabled_mappings):
        warnings.append("여러 지표가 동일 ITM_ID를 공유합니다. KOSIS 응답을 확인하세요.")
    if ready and len(class_ids) != len(enabled_mappings):
        warnings.append("여러 지표가 동일 C1_ID를 공유합니다. KOSIS 응답을 확인하세요.")

    return {
        "connection_id": table.get("connection_id"),
        "purpose": table.get("purpose"),
        "secret_name": table.get("secret_name"),
        "status": "ready" if ready else "mapping_required",
        "ready": ready,
        "errors": list(dict.fromkeys(errors)),
        "warnings": warnings,
        "metric_count": len(enabled_mappings),
        "ready_metric_count": sum(1 for x in metric_results if x["ready"]),
        "item_ids": item_ids,
        "class_ids": class_ids,
        "candidate_url_template": candidate_url,
        "masked_url": masked_url(candidate_url, api_key_placeholder) if candidate_url else None,
        "metrics": metric_results,
        "next_action": "KOSIS_API_KEY로 런타임 호출 가능" if ready else "운영 승격 또는 코드 승인을 먼저 완료",
    }


def main() -> int:
    mapping_doc, runtime = resolve_mapping()
    policy = read_json(POLICY_PATH, {})
    rows = [build_table(table, mapping_doc, policy) for table in mapping_doc.get("tables", []) or []]
    ready_count = sum(1 for row in rows if row["ready"])
    status = "ready" if rows and ready_count == len(rows) else ("partial" if ready_count else "mapping_required")
    payload = {
        "updated_at": now_iso(),
        "policy": "phase9_kosis_url_generator_runtime_v1",
        "summary": {
            "status": status,
            "table_count": len(rows),
            "ready_table_count": ready_count,
            "generated_url_count": ready_count,
            "secret_count": len([x for x in rows if x.get("secret_name")]),
            "mapping_source": runtime["mapping_source"],
            "operational_mapping_active": runtime["mapping_source"] == "operational",
            "fallback_used": runtime["fallback_used"],
        },
        "runtime_mapping": runtime,
        "tables": rows,
        "security": policy.get("security") or {},
        "notice": "승격된 운영 매핑을 우선 사용하며, 미승격 상태에서는 기존 템플릿을 안전하게 유지합니다.",
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

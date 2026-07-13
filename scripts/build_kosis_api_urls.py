#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build KOSIS API candidate URLs from the approved mapping template.

Security rules:
- Never read or persist a real API key.
- Emit {API_KEY} placeholders only.
- Refuse to mark a URL ready while table or mapping placeholders remain.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
MAPPING_PATH = DATA / "config" / "kosis_table_mapping_template.json"
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
    placeholders = list((mapping_doc.get("instructions") or {}).get("placeholder_values") or [])
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
        if has_placeholder(item_id, placeholders):
            metric_errors.append("ITM_ID 미설정")
        if has_placeholder(class_id, placeholders):
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
            "item_id": item_id if not has_placeholder(item_id, placeholders) else None,
            "class_id": class_id if not has_placeholder(class_id, placeholders) else None,
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
    candidate_url = f"{policy.get('endpoint')}?{urlencode(query, safe='{},') }" if ready else None
    if ready and len(item_ids) != len(enabled_mappings):
        warnings.append("여러 지표가 동일 ITM_ID를 공유합니다. KOSIS 응답을 브라우저에서 확인하세요.")
    if ready and len(class_ids) != len(enabled_mappings):
        warnings.append("여러 지표가 동일 C1_ID를 공유합니다. KOSIS 응답을 브라우저에서 확인하세요.")

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
        "next_action": "{API_KEY}를 실제 키로 바꿔 브라우저에서 응답 확인 후 전체 URL을 Secret에 등록" if ready else "KOSIS 실제 코드 입력 화면에서 누락 코드를 먼저 입력",
    }


def main() -> int:
    mapping_doc = read_json(MAPPING_PATH, {"tables": []})
    policy = read_json(POLICY_PATH, {})
    rows = [build_table(table, mapping_doc, policy) for table in mapping_doc.get("tables", []) or []]
    ready_count = sum(1 for row in rows if row["ready"])
    status = "ready" if rows and ready_count == len(rows) else ("partial" if ready_count else "mapping_required")
    payload = {
        "updated_at": now_iso(),
        "policy": "phase8_kosis_url_generator_v1",
        "summary": {
            "status": status,
            "table_count": len(rows),
            "ready_table_count": ready_count,
            "generated_url_count": ready_count,
            "secret_count": len([x for x in rows if x.get("secret_name")]),
        },
        "tables": rows,
        "security": policy.get("security") or {},
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

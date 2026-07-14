#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate approved KOSIS mapping and promote it to the operational mapping.

Promotion is explicit and fail-closed. The approved mapping, source template and API
credentials are never modified. An existing operational mapping is preserved when
validation or approval is incomplete.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
APPROVED = DATA / "config" / "kosis_table_mapping_approved.json"
PROMOTION = DATA / "admin" / "kosis_mapping_promotion_approvals.json"
OPERATIONAL = DATA / "config" / "kosis_table_mapping_operational.json"
ADMIN_OUT = DATA / "admin" / "kosis_mapping_promotion_status.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_mapping_promotion_status.json"
PLACEHOLDERS = ["REPLACE_", "PLACEHOLDER", "TODO"]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def invalid(value: Any) -> bool:
    if value in (None, "", [], {}):
        return True
    if isinstance(value, str):
        return any(token in value.upper() for token in PLACEHOLDERS)
    return False


def validate(doc: dict) -> tuple[list[str], list[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_metrics: set[str] = set()
    seen_connections: set[str] = set()
    tables = doc.get("tables") or []
    if not tables:
        errors.append("승인 매핑 테이블 없음")
    for ti, table in enumerate(tables):
        label = str(table.get("connection_id") or f"table[{ti}]")
        if label in seen_connections:
            errors.append(f"중복 connection_id: {label}")
        seen_connections.add(label)
        for field in ("connection_id", "secret_name", "org_id", "tbl_id", "period", "start_prd_de", "end_prd_de"):
            if invalid(table.get(field)):
                errors.append(f"{label}: {field} 누락")
        if not table.get("selected"):
            errors.append(f"{label}: selected=false")
        mappings = [x for x in table.get("metric_mappings", []) or [] if x.get("enabled", True)]
        if not mappings:
            errors.append(f"{label}: 활성 지표 없음")
        for mapping in mappings:
            metric = str(mapping.get("metric_id") or "")
            item = (mapping.get("item_selector") or {}).get("ITM_ID")
            cls = (mapping.get("classification_selectors") or {}).get("C1_ID")
            if invalid(metric): errors.append(f"{label}: metric_id 누락")
            elif metric in seen_metrics: errors.append(f"중복 metric_id: {metric}")
            else: seen_metrics.add(metric)
            if invalid(mapping.get("species")): errors.append(f"{metric or label}: species 누락")
            if invalid(item): errors.append(f"{metric or label}: ITM_ID 누락")
            if invalid(cls): errors.append(f"{metric or label}: C1_ID 누락")
            if not mapping.get("unit_expectation"): errors.append(f"{metric or label}: 단위 누락")
            if not mapping.get("approval_evidence"):
                warnings.append(f"{metric or label}: approval_evidence 미기록")
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings)), seen_metrics


def main() -> int:
    checked_at = now_iso()
    approved = read_json(APPROVED, {"tables": []})
    registry = read_json(PROMOTION, {"promotion": {}})
    promotion = registry.get("promotion") or {}
    errors, warnings, metrics = validate(approved)
    decision = str(promotion.get("decision") or "pending")
    reviewer = str(promotion.get("reviewer") or "").strip()
    expected = str(promotion.get("expected_mapping_policy") or "")
    source_policy = str(approved.get("policy") or "")
    if decision != "approve": errors.append("운영 승격 승인 필요")
    if not reviewer: errors.append("승격 검수자 누락")
    if expected and expected != source_policy: errors.append("승인 대상 매핑 정책 불일치")
    ready = not errors
    if ready:
        operational = deepcopy(approved)
        operational.update({
            "updated_at": checked_at,
            "policy": "phase9_kosis_operational_mapping_v1",
            "promotion_status": "promoted",
            "source_mapping_policy": source_policy,
            "promoted_at": checked_at,
            "promoted_by": reviewer,
            "promotion_note": promotion.get("note"),
        })
        write_json(OPERATIONAL, operational)
    current = read_json(OPERATIONAL, {"tables": []})
    payload = {
        "updated_at": checked_at,
        "policy": "phase9_kosis_mapping_promotion_v1",
        "summary": {
            "status": "promoted" if ready else ("validation_failed" if errors and decision == "approve" else "approval_required"),
            "approved_table_count": len(approved.get("tables") or []),
            "validated_metric_count": len(metrics),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "promotion_decision": decision,
            "operational_table_count": len(current.get("tables") or []),
            "source_template_modified": False,
            "approved_mapping_modified": False,
        },
        "errors": errors,
        "warnings": warnings,
        "operational_mapping_path": str(OPERATIONAL.relative_to(ROOT)),
        "promotion_registry_path": str(PROMOTION.relative_to(ROOT)),
        "notice": "승인 매핑 검증과 명시적 승격 승인이 모두 통과한 경우에만 운영 매핑을 갱신합니다. 실패 시 기존 운영 매핑을 보존합니다."
    }
    write_json(ADMIN_OUT, payload); write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

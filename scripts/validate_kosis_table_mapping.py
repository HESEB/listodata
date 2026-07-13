#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate KOSIS table selection and DSS metric mappings.

The validator never requires or prints an API key. It checks whether table IDs,
item/classification selectors, units and DSS catalog metric IDs are ready.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
TEMPLATE = DATA / "config" / "kosis_table_mapping_template.json"
CATALOG = DATA / "design" / "official_data_catalog.json"
ADMIN_OUT = DATA / "admin" / "kosis_table_mapping_status.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_table_mapping_status.json"


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


def catalog_index(catalog: dict) -> dict[str, dict]:
    out = {}
    for species, meta in (catalog.get("species") or {}).items():
        for metric in meta.get("required_metrics", []) or []:
            row = dict(metric)
            row["species"] = species
            out[str(metric.get("metric_id"))] = row
    return out


def contains_placeholder(value: Any, placeholders: list[str]) -> bool:
    if isinstance(value, str):
        return not value.strip() or any(x in value for x in placeholders)
    if isinstance(value, dict):
        return any(contains_placeholder(v, placeholders) for v in value.values())
    if isinstance(value, list):
        return any(contains_placeholder(v, placeholders) for v in value)
    return value is None


def main() -> int:
    template = read_json(TEMPLATE, {"tables": []})
    catalog = catalog_index(read_json(CATALOG, {}))
    placeholders = list((template.get("instructions") or {}).get("placeholder_values") or [])
    required_table = list((template.get("instructions") or {}).get("required_table_fields") or [])
    required_mapping = list((template.get("instructions") or {}).get("required_mapping_fields") or [])

    table_results = []
    seen_metrics: dict[str, str] = {}
    mapped_metrics = set()
    duplicate_metrics = []
    total_mappings = 0
    ready_mappings = 0

    for table in template.get("tables", []) or []:
        table_errors = []
        table_warnings = []
        for field in required_table:
            if contains_placeholder(table.get(field), placeholders):
                table_errors.append(f"{field} 미설정")
        if not table.get("secret_name"):
            table_errors.append("secret_name 누락")
        if not table.get("selected"):
            table_warnings.append("통계표 선정 확인 미완료")

        mapping_results = []
        for mapping in table.get("metric_mappings", []) or []:
            if not mapping.get("enabled", True):
                continue
            total_mappings += 1
            errors = []
            warnings = []
            metric_id = str(mapping.get("metric_id") or "")
            for field in required_mapping:
                if field not in mapping or mapping.get(field) in (None, "", [], {}):
                    errors.append(f"{field} 누락")
            if metric_id not in catalog:
                errors.append("DSS 카탈로그 미등록 metric_id")
            else:
                expected_species = catalog[metric_id].get("species")
                if mapping.get("species") != expected_species:
                    errors.append(f"축종 불일치: catalog={expected_species}")
            if metric_id in seen_metrics:
                duplicate_metrics.append(metric_id)
                errors.append(f"중복 매핑: {seen_metrics[metric_id]}")
            elif metric_id:
                seen_metrics[metric_id] = table.get("connection_id")
            if contains_placeholder(mapping.get("item_selector"), placeholders):
                errors.append("항목코드 미설정")
            if contains_placeholder(mapping.get("classification_selectors"), placeholders):
                errors.append("분류코드 미설정")
            units = mapping.get("unit_expectation") or []
            if not units:
                errors.append("예상 단위 누락")
            elif any(contains_placeholder(x, placeholders) for x in units):
                warnings.append("예상 단위 확인 필요")
            ready = not errors and bool(table.get("selected"))
            if ready:
                ready_mappings += 1
                mapped_metrics.add(metric_id)
            mapping_results.append({
                "metric_id": metric_id,
                "species": mapping.get("species"),
                "ready": ready,
                "errors": errors,
                "warnings": warnings,
                "catalog_name": (catalog.get(metric_id) or {}).get("name"),
                "unit_expectation": units,
            })

        status = "ready" if not table_errors and table.get("selected") and mapping_results and all(x["ready"] for x in mapping_results) else ("partial" if mapping_results else "not_configured")
        table_results.append({
            "connection_id": table.get("connection_id"),
            "purpose": table.get("purpose"),
            "secret_name": table.get("secret_name"),
            "status": status,
            "selected": bool(table.get("selected")),
            "org_id_configured": not contains_placeholder(table.get("org_id"), placeholders),
            "tbl_id_configured": not contains_placeholder(table.get("tbl_id"), placeholders),
            "errors": table_errors,
            "warnings": table_warnings,
            "mappings": mapping_results,
        })

    target_metrics = set(seen_metrics)
    configured_count = sum(1 for x in table_results if x["status"] == "ready")
    status = "ready" if table_results and configured_count == len(table_results) and ready_mappings == total_mappings else ("partial" if ready_mappings or any(x["selected"] for x in table_results) else "selection_required")
    payload = {
        "updated_at": now_iso(),
        "policy": "phase8_kosis_table_mapping_v1",
        "summary": {
            "status": status,
            "table_count": len(table_results),
            "ready_table_count": configured_count,
            "mapping_count": total_mappings,
            "ready_mapping_count": ready_mappings,
            "duplicate_metric_count": len(set(duplicate_metrics)),
            "target_metric_count": len(target_metrics),
        },
        "tables": table_results,
        "duplicate_metrics": sorted(set(duplicate_metrics)),
        "mapped_metrics": sorted(mapped_metrics),
        "target_metrics": sorted(target_metrics),
        "notice": "실제 KOSIS 기관코드·통계표ID·항목코드·분류코드 입력 전에는 selection_required가 정상입니다. 인증키는 검증 대상이 아닙니다.",
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

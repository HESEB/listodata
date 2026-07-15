#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare generated approved KOSIS mapping with template, previous approved, and operational mappings."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
TEMPLATE = DATA / "config" / "kosis_table_mapping_template.json"
APPROVED = DATA / "config" / "kosis_table_mapping_approved.json"
PREVIOUS = DATA / "admin" / "kosis_table_mapping_approved_previous.json"
OPERATIONAL = DATA / "config" / "kosis_table_mapping_operational.json"
PRECHECK = DATA / "admin" / "kosis_approval_precheck.json"
GENERATION = DATA / "admin" / "kosis_mapping_generation.json"
POLICY = DATA / "config" / "kosis_approved_mapping_comparison_policy.json"
ADMIN_OUT = DATA / "admin" / "kosis_approved_mapping_comparison.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_approved_mapping_comparison.json"


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


def metric_index(doc: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for table in doc.get("tables", []) or []:
        if not isinstance(table, dict):
            continue
        for metric in table.get("metric_mappings", []) or []:
            if not isinstance(metric, dict) or not metric.get("metric_id"):
                continue
            out[str(metric["metric_id"])] = {
                "connection_id": table.get("connection_id"),
                "org_id": table.get("org_id"),
                "tbl_id": table.get("tbl_id"),
                "period": table.get("period"),
                "selected": table.get("selected"),
                "ITM_ID": (metric.get("item_selector") or {}).get("ITM_ID"),
                "C1_ID": (metric.get("classification_selectors") or {}).get("C1_ID"),
                "unit_expectation": metric.get("unit_expectation") or [],
                "species": metric.get("species"),
                "enabled": metric.get("enabled", True),
            }
    return out


def normalize(value: Any) -> Any:
    if isinstance(value, list):
        return sorted(str(x) for x in value)
    return value


def diff_one(base: dict[str, dict], current: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for metric_id in sorted(set(base) | set(current)):
        before = base.get(metric_id)
        after = current.get(metric_id)
        if before is None:
            rows.append({"metric_id": metric_id, "change_type": "added", "before": None, "after": after, "changed_fields": list(after or {})})
            continue
        if after is None:
            rows.append({"metric_id": metric_id, "change_type": "removed", "before": before, "after": None, "changed_fields": list(before or {})})
            continue
        changed = [k for k in sorted(set(before) | set(after)) if normalize(before.get(k)) != normalize(after.get(k))]
        if not changed:
            change_type = "unchanged"
        elif any(k in changed for k in ("ITM_ID", "C1_ID")):
            change_type = "code_changed"
        elif "unit_expectation" in changed:
            change_type = "unit_changed"
        elif "period" in changed:
            change_type = "period_changed"
        elif any(k in changed for k in ("connection_id", "org_id", "tbl_id", "selected")):
            change_type = "table_changed"
        else:
            change_type = "changed"
        rows.append({"metric_id": metric_id, "change_type": change_type, "before": before, "after": after, "changed_fields": changed})
    return rows


def counts(rows: list[dict]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = str(row.get("change_type") or "unknown")
        result[key] = result.get(key, 0) + 1
    return result


def main() -> int:
    generated_at = now_iso()
    template = read_json(TEMPLATE, {"tables": []})
    approved = read_json(APPROVED, {"tables": [], "generation_summary": {}})
    previous_wrapper = read_json(PREVIOUS, {"mapping": {"tables": []}})
    previous = previous_wrapper.get("mapping") or {"tables": []}
    operational = read_json(OPERATIONAL, {"tables": []})
    precheck = read_json(PRECHECK, {"summary": {}})
    generation = read_json(GENERATION, {"summary": {}})
    policy = read_json(POLICY, {})

    current_idx = metric_index(approved)
    comparisons = {
        "template": diff_one(metric_index(template), current_idx),
        "previous_approved": diff_one(metric_index(previous), current_idx),
        "operational": diff_one(metric_index(operational), current_idx),
    }
    changed_from_previous = [x for x in comparisons["previous_approved"] if x["change_type"] != "unchanged"]
    changed_from_template = [x for x in comparisons["template"] if x["change_type"] != "unchanged"]
    generation_summary = approved.get("generation_summary") or generation.get("summary") or {}
    precheck_summary = precheck.get("summary") or {}

    if not current_idx:
        status = "approval_mapping_required"
    elif not precheck_summary.get("mapping_generation_allowed") and generation_summary.get("approval_count", 0):
        status = "precheck_blocked"
    elif generation_summary.get("status") == "ready":
        status = "ready_for_dry_run"
    elif generation_summary.get("status") == "partial":
        status = "partial_mapping"
    else:
        status = "comparison_ready"

    summary = {
        "status": status,
        "approved_metric_count": int(generation_summary.get("mapped_metric_count") or 0),
        "target_metric_count": int(generation_summary.get("target_metric_count") or len(current_idx)),
        "unresolved_metric_count": int(generation_summary.get("unresolved_metric_count") or 0),
        "changed_from_template_count": len(changed_from_template),
        "changed_from_previous_count": len(changed_from_previous),
        "operational_difference_count": sum(1 for x in comparisons["operational"] if x["change_type"] != "unchanged"),
        "precheck_allowed": bool(precheck_summary.get("mapping_generation_allowed")),
        "source_template_modified": False,
        "operational_mapping_modified": False,
    }
    payload = {
        "updated_at": generated_at,
        "policy": "phase10_kosis_approved_mapping_comparison_v1",
        "summary": summary,
        "change_counts": {name: counts(rows) for name, rows in comparisons.items()},
        "comparisons": comparisons,
        "previous_approved": {
            "preserved_at": previous_wrapper.get("preserved_at"),
            "source_updated_at": previous_wrapper.get("source_updated_at"),
        },
        "generation_summary": generation_summary,
        "next_action": "승인 매핑 변경사항을 검수한 뒤 실제 KOSIS 응답 Dry Run을 진행하세요." if status in {"ready_for_dry_run", "comparison_ready"} else "승인·사전점검·미해결 지표를 먼저 정리하세요.",
        "security": {"api_key_exposed": False, "request_url_exposed": False},
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

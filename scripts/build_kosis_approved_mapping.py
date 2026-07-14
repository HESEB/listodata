#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a reviewable KOSIS mapping from administrator-approved detail candidates.

The source template is never overwritten. Only approvals with matching official
research evidence and complete org/table/item/classification codes are emitted.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
DETAIL = DATA / "analysis" / "kosis_detail_research.json"
APPROVALS = DATA / "admin" / "kosis_detail_approvals.json"
TEMPLATE = DATA / "config" / "kosis_table_mapping_template.json"
OUT_CONFIG = DATA / "config" / "kosis_table_mapping_approved.json"
OUT_ADMIN = DATA / "admin" / "kosis_mapping_generation.json"
OUT_ANALYSIS = DATA / "analysis" / "kosis_mapping_generation.json"


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


def evidence_index(detail: dict) -> dict[tuple[str, str, str, str, str], dict]:
    index: dict[tuple[str, str, str, str, str], dict] = {}
    for target in detail.get("targets", []) or []:
        rid = str(target.get("research_id") or "")
        for table in target.get("tables", []) or []:
            org_id, tbl_id = str(table.get("org_id") or ""), str(table.get("tbl_id") or "")
            for metric in table.get("metrics", []) or []:
                metric_id = str(metric.get("metric_id") or "")
                for candidate in metric.get("candidates", []) or []:
                    if not isinstance(candidate, dict):
                        continue
                    key = (metric_id, org_id, tbl_id, str(candidate.get("ITM_ID") or ""), str(candidate.get("C1_ID") or ""))
                    index[key] = {"research_id": rid, "table": table, "metric": metric, "candidate": candidate}
    return index


def main() -> int:
    generated_at = now_iso()
    detail = read_json(DETAIL, {"targets": [], "summary": {}})
    approvals_doc = read_json(APPROVALS, {"approvals": []})
    template = read_json(TEMPLATE, {"tables": []})
    evidence = evidence_index(detail)

    approved_rows: list[dict] = []
    rejected_rows: list[dict] = []
    duplicate_keys: set[tuple[str, str, str, str, str]] = set()
    seen_metrics: set[str] = set()

    for position, row in enumerate(approvals_doc.get("approvals", []) or []):
        if not isinstance(row, dict):
            rejected_rows.append({"position": position, "reason": "approval 형식 오류"})
            continue
        if str(row.get("decision") or "") != "approve":
            continue
        key = (
            str(row.get("metric_id") or ""), str(row.get("org_id") or ""),
            str(row.get("tbl_id") or ""), str(row.get("ITM_ID") or ""),
            str(row.get("C1_ID") or ""),
        )
        missing = [name for name, value in zip(("metric_id", "org_id", "tbl_id", "ITM_ID", "C1_ID"), key) if not value]
        if missing:
            rejected_rows.append({"position": position, "metric_id": key[0], "reason": "필수 코드 누락", "missing": missing})
            continue
        if key in duplicate_keys or key[0] in seen_metrics:
            rejected_rows.append({"position": position, "metric_id": key[0], "reason": "중복 승인"})
            continue
        match = evidence.get(key)
        if not match:
            rejected_rows.append({"position": position, "metric_id": key[0], "reason": "현재 공식 상세 조사 근거와 불일치"})
            continue
        candidate = match["candidate"]
        if candidate.get("evidence_status") != "complete":
            rejected_rows.append({"position": position, "metric_id": key[0], "reason": "상세 근거 불완전"})
            continue
        duplicate_keys.add(key); seen_metrics.add(key[0])
        approved_rows.append({**row, "research_id": match["research_id"], "table_name": match["table"].get("table_name"), "period": match["table"].get("period"), "ITM_NM": candidate.get("ITM_NM"), "C1_NM": candidate.get("C1_NM"), "UNIT_NM": candidate.get("UNIT_NM"), "official_response_checked_at": match["table"].get("official_response_checked_at")})

    generated = copy.deepcopy(template)
    generated["updated_at"] = generated_at
    generated["policy"] = "phase9_kosis_approved_mapping_v1"
    generated["source_template"] = str(TEMPLATE.relative_to(ROOT))
    generated["approval_registry"] = str(APPROVALS.relative_to(ROOT))
    generated["notice"] = "관리자 승인과 현재 공식 상세 API 근거가 일치한 코드만 생성했습니다. 원본 템플릿은 변경하지 않았습니다."

    approved_by_metric = {row["metric_id"]: row for row in approved_rows}
    table_ready: dict[str, bool] = {}
    for table in generated.get("tables", []) or []:
        mapped = []
        table_codes: set[tuple[str, str]] = set()
        for metric in table.get("metric_mappings", []) or []:
            approval = approved_by_metric.get(str(metric.get("metric_id") or ""))
            if approval:
                metric["item_selector"]["ITM_ID"] = approval["ITM_ID"]
                metric["classification_selectors"]["C1_ID"] = approval["C1_ID"]
                if approval.get("ITM_NM"):
                    metric["item_selector"]["ITM_NM_contains"] = [approval["ITM_NM"]]
                if approval.get("C1_NM"):
                    metric["classification_selectors"]["C1_NM_contains"] = [approval["C1_NM"]]
                if approval.get("UNIT_NM"):
                    metric["unit_expectation"] = [approval["UNIT_NM"]]
                metric["approval_evidence"] = {k: approval.get(k) for k in ("approved_at", "reviewer", "note", "official_response_checked_at")}
                table_codes.add((approval["org_id"], approval["tbl_id"])); mapped.append(metric["metric_id"])
        if len(table_codes) == 1 and mapped:
            org_id, tbl_id = next(iter(table_codes)); table["org_id"] = org_id; table["tbl_id"] = tbl_id
            table["selected"] = True; table["selection_note"] = f"관리자 승인 지표 {len(mapped)}건 기반 자동 생성"
            table_ready[str(table.get("connection_id"))] = True
        else:
            table["selected"] = False
            table["selection_note"] = "승인 지표 없음 또는 한 연결에 서로 다른 통계표가 혼재하여 분리 필요"
            table_ready[str(table.get("connection_id"))] = False

    placeholders = set((template.get("instructions") or {}).get("placeholder_values") or [])
    unresolved_metrics = []
    for table in generated.get("tables", []) or []:
        for metric in table.get("metric_mappings", []) or []:
            values = [metric.get("item_selector", {}).get("ITM_ID"), metric.get("classification_selectors", {}).get("C1_ID")]
            if any(value in placeholders or not value for value in values):
                unresolved_metrics.append(metric.get("metric_id"))

    status = "ready" if approved_rows and not unresolved_metrics and all(table_ready.values()) else ("partial" if approved_rows else "approval_required")
    summary = {
        "status": status,
        "approval_count": len(approved_rows),
        "rejected_approval_count": len(rejected_rows),
        "mapped_metric_count": len(approved_rows),
        "target_metric_count": sum(len(x.get("metric_mappings", []) or []) for x in generated.get("tables", []) or []),
        "unresolved_metric_count": len(unresolved_metrics),
        "ready_table_count": sum(1 for value in table_ready.values() if value),
        "auto_applied_to_source_template": False,
    }
    generated["generation_summary"] = summary
    write_json(OUT_CONFIG, generated)
    payload = {"updated_at": generated_at, "policy": "phase9_kosis_mapping_generation_v1", "summary": summary, "approved": approved_rows, "rejected_approvals": rejected_rows, "unresolved_metrics": unresolved_metrics, "generated_path": str(OUT_CONFIG.relative_to(ROOT)), "source_template_unchanged": True, "notice": "승인 생성본은 별도 파일입니다. 검증 후 운영 매핑으로 승격해야 합니다."}
    write_json(OUT_ADMIN, payload); write_json(OUT_ANALYSIS, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

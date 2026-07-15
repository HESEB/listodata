#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Score KOSIS detail candidates and select manual-review priorities.

The scorer never approves or applies mappings. It only ranks candidates already
present in official detail-research output.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
DETAIL = DATA / "analysis" / "kosis_detail_research.json"
TARGETS = DATA / "config" / "kosis_code_research_targets.json"
POLICY = DATA / "config" / "kosis_candidate_quality_policy.json"
ADMIN_OUT = DATA / "admin" / "kosis_candidate_quality.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_candidate_quality.json"


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


def text(value: Any) -> str:
    return str(value or "").strip()


def target_index(doc: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for target in doc.get("targets", []) or []:
        meta = {
            "research_id": target.get("research_id"),
            "keywords": target.get("keywords") or [],
            "period_expected": target.get("period_expected"),
        }
        for metric_id in target.get("metrics", []) or []:
            result[str(metric_id)] = meta
    return result


def rows_from_detail(doc: dict) -> list[dict]:
    rows: list[dict] = []
    for target in doc.get("targets", []) or []:
        research_id = target.get("research_id")
        for table in target.get("tables", []) or []:
            for metric in table.get("metrics", []) or []:
                metric_id = text(metric.get("metric_id"))
                for candidate in metric.get("candidates", []) or []:
                    if not isinstance(candidate, dict):
                        continue
                    rows.append({
                        "research_id": research_id,
                        "metric_id": metric_id,
                        "org_id": text(table.get("org_id") or candidate.get("org_id")),
                        "tbl_id": text(table.get("tbl_id") or candidate.get("tbl_id")),
                        "table_name": text(table.get("table_name") or candidate.get("table_name")),
                        "period": text(table.get("period") or candidate.get("period")),
                        "official_response_checked_at": table.get("official_response_checked_at") or candidate.get("official_response_checked_at"),
                        "ITM_ID": text(candidate.get("ITM_ID")),
                        "ITM_NM": text(candidate.get("ITM_NM")),
                        "C1_ID": text(candidate.get("C1_ID")),
                        "C1_NM": text(candidate.get("C1_NM")),
                        "UNIT_NM": text(candidate.get("UNIT_NM")),
                        "evidence_status": text(candidate.get("evidence_status")),
                    })
    return rows


def priority(score: int, thresholds: dict) -> str:
    for label in ("P1", "P2", "P3"):
        if score >= int(thresholds.get(label, 0)):
            return label
    return "HOLD"


def main() -> int:
    generated_at = now_iso()
    detail = read_json(DETAIL, {"summary": {}, "targets": [], "errors": []})
    targets = target_index(read_json(TARGETS, {"targets": []}))
    policy = read_json(POLICY, {})
    weights = policy.get("weights") or {}
    penalties = policy.get("penalties") or {}
    thresholds = policy.get("priority_thresholds") or {}
    rows = rows_from_detail(detail)

    metric_counts: dict[str, int] = {}
    for row in rows:
        metric_counts[row["metric_id"]] = metric_counts.get(row["metric_id"], 0) + 1

    scored: list[dict] = []
    for row in rows:
        score = 0
        reasons: list[str] = []
        risks: list[str] = []
        meta = targets.get(row["metric_id"], {})
        complete = row["evidence_status"] == "complete"
        if complete:
            score += int(weights.get("complete_official_evidence", 25)); reasons.append("공식 상세 근거 complete")
        else:
            score -= int(penalties.get("incomplete_evidence", 25)); risks.append("공식 상세 근거 불완전")

        if row["org_id"] and row["tbl_id"]:
            score += int(weights.get("org_and_table_codes", 15)); reasons.append("기관·통계표 코드 확인")
        else:
            score -= int(penalties.get("missing_required_code", 30)); risks.append("기관 또는 통계표 코드 누락")

        if row["ITM_ID"] and row["C1_ID"]:
            score += int(weights.get("item_and_classification_codes", 20)); reasons.append("항목·분류 코드 확인")
        else:
            score -= int(penalties.get("missing_required_code", 30)); risks.append("ITM_ID 또는 C1_ID 누락")

        if row["official_response_checked_at"]:
            score += int(weights.get("official_response_checked_at", 10)); reasons.append("공식 응답 확인시각 존재")
        else:
            risks.append("공식 응답 확인시각 없음")

        if row["UNIT_NM"]:
            score += int(weights.get("unit_present", 8)); reasons.append("단위 확인")
        else:
            score -= int(penalties.get("missing_unit", 8)); risks.append("단위 누락")

        haystack = " ".join([row["table_name"], row["ITM_NM"], row["C1_NM"]]).lower()
        hits = [kw for kw in meta.get("keywords", []) if text(kw).lower() in haystack]
        if hits:
            score += int(weights.get("target_keyword_match", 10)); reasons.append("대상 키워드 일치: " + ", ".join(hits[:3]))
        else:
            risks.append("대상 키워드 직접 일치 없음")

        expected = text(meta.get("period_expected"))
        if expected and row["period"] == expected:
            score += int(weights.get("expected_period_match", 7)); reasons.append("예상 주기 일치")
        elif expected:
            score -= int(penalties.get("period_mismatch", 12)); risks.append(f"주기 불일치: expected={expected}, actual={row['period'] or 'missing'}")

        if metric_counts.get(row["metric_id"], 0) == 1:
            score += int(weights.get("unique_metric_candidate", 5)); reasons.append("해당 지표 단일 후보")
        else:
            score -= int(penalties.get("duplicate_metric_candidate", 10)); risks.append(f"동일 지표 후보 {metric_counts.get(row['metric_id'], 0)}건")

        score = max(0, min(100, score))
        scored.append({**row, "quality_score": score, "priority": priority(score, thresholds), "score_reasons": reasons, "risk_flags": risks})

    scored.sort(key=lambda x: (-x["quality_score"], x["metric_id"], x["tbl_id"], x["ITM_ID"], x["C1_ID"]))
    recommended_metrics: set[str] = set()
    for row in scored:
        row["recommended_for_review"] = row["priority"] in {"P1", "P2"} and row["metric_id"] not in recommended_metrics
        if row["recommended_for_review"]:
            recommended_metrics.add(row["metric_id"])

    max_rows = int((policy.get("review_rules") or {}).get("maximum_priority_rows", 30))
    priority_queue = [row for row in scored if row["priority"] != "HOLD"][:max_rows]
    detail_status = text((detail.get("summary") or {}).get("status"))
    if not rows:
        status = "candidate_generation_required" if detail_status in {"credential_required", "research_required", ""} else "no_candidates"
    elif recommended_metrics:
        status = "priority_review_ready"
    else:
        status = "manual_review_required"

    summary = {
        "status": status,
        "candidate_count": len(scored),
        "priority_queue_count": len(priority_queue),
        "recommended_metric_count": len(recommended_metrics),
        "p1_count": sum(1 for x in scored if x["priority"] == "P1"),
        "p2_count": sum(1 for x in scored if x["priority"] == "P2"),
        "p3_count": sum(1 for x in scored if x["priority"] == "P3"),
        "hold_count": sum(1 for x in scored if x["priority"] == "HOLD"),
        "auto_approved_count": 0,
        "auto_applied_count": 0,
    }
    payload = {
        "updated_at": generated_at,
        "policy": "phase10_kosis_candidate_quality_v1",
        "summary": summary,
        "priority_queue": priority_queue,
        "candidates": scored,
        "thresholds": thresholds,
        "source_status": detail_status,
        "next_action": "P1부터 공식 통계표·항목·분류·단위를 확인한 뒤 상세후보 승인 화면에서 결정하세요." if rows else "KOSIS_API_KEY 등록 후 Update market data를 실행해 후보를 생성하세요.",
        "security": {"api_key_exposed": False, "request_url_exposed": False},
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

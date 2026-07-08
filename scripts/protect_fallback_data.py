#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Protect fallback data for HESEB Livestock Terminal.

Modes:
  snapshot: copy current valid critical JSON files into app/data/fallback
  restore : restore invalid/missing critical JSON files from fallback snapshot
  verify  : report fallback coverage only

This is designed for GitHub Pages static data. It protects the last known valid
JSON files when a scheduled update fails or produces broken data.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
FALLBACK = DATA / "fallback"
ADMIN = DATA / "admin"
ANALYSIS = DATA / "analysis"

CRITICAL_FILES = [
    "market_dashboard.json",
    "market_metrics.json",
    "update_status.json",
    "system/version.json",
    "events/events_news.json",
    "events/events_official.json",
    "events/event_calendar.json",
    "raw/events_raw.json",
    "clean/events_clean.json",
    "clean/events_rejected.json",
    "analysis/evidence_scores.json",
    "analysis/evidence_chains.json",
    "analysis/cross_market_matrix.json",
    "analysis/conflict_report.json",
    "analysis/history_prediction.json",
    "analysis/market_memory.json",
    "analysis/case_comparison.json",
    "analysis/classification_review.json",
    "analysis/change_log.json",
    "analysis/update_stability.json",
    "history/signal_history.json",
    "display/market_dashboard_phase1.json",
    "admin/quality_report.json",
    "admin/conflict_report.json",
    "admin/cross_market_matrix.json",
    "admin/history_prediction.json",
    "admin/market_memory.json",
    "admin/case_comparison.json",
    "admin/classification_review.json",
    "admin/change_log.json",
    "admin/update_stability.json",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def data_path(rel_path: str) -> Path:
    return DATA / rel_path


def fallback_path(rel_path: str) -> Path:
    return FALLBACK / rel_path


def is_valid_json(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        if path.stat().st_size <= 2:
            return False, "too_small"
        json.loads(path.read_text(encoding="utf-8"))
        return True, "ok"
    except Exception as exc:
        return False, f"parse_error: {exc}"


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot() -> dict:
    rows = []
    for rel_path in CRITICAL_FILES:
        src = data_path(rel_path)
        dst = fallback_path(rel_path)
        valid, reason = is_valid_json(src)
        row = {"path": "app/data/" + rel_path, "fallback_path": "app/data/fallback/" + rel_path, "valid": valid, "reason": reason, "action": "skip"}
        if valid:
            copy_file(src, dst)
            row["action"] = "snapshot"
        rows.append(row)
    return build_status("snapshot", rows)


def restore() -> dict:
    rows = []
    for rel_path in CRITICAL_FILES:
        src = data_path(rel_path)
        fb = fallback_path(rel_path)
        cur_valid, cur_reason = is_valid_json(src)
        fb_valid, fb_reason = is_valid_json(fb)
        row = {
            "path": "app/data/" + rel_path,
            "fallback_path": "app/data/fallback/" + rel_path,
            "current_valid": cur_valid,
            "current_reason": cur_reason,
            "fallback_valid": fb_valid,
            "fallback_reason": fb_reason,
            "action": "keep_current",
        }
        if not cur_valid and fb_valid:
            copy_file(fb, src)
            row["action"] = "restore_from_fallback"
        elif not cur_valid and not fb_valid:
            row["action"] = "restore_failed_no_valid_fallback"
        rows.append(row)
    return build_status("restore", rows)


def verify() -> dict:
    rows = []
    for rel_path in CRITICAL_FILES:
        fb = fallback_path(rel_path)
        valid, reason = is_valid_json(fb)
        rows.append({"path": "app/data/" + rel_path, "fallback_path": "app/data/fallback/" + rel_path, "fallback_valid": valid, "reason": reason})
    return build_status("verify", rows)


def build_status(mode: str, rows: list[dict]) -> dict:
    if mode == "snapshot":
        ok = sum(1 for r in rows if r.get("action") == "snapshot")
        fail = sum(1 for r in rows if r.get("action") != "snapshot")
        restored = 0
    elif mode == "restore":
        ok = sum(1 for r in rows if r.get("current_valid") or r.get("action") == "restore_from_fallback")
        fail = sum(1 for r in rows if r.get("action") == "restore_failed_no_valid_fallback")
        restored = sum(1 for r in rows if r.get("action") == "restore_from_fallback")
    else:
        ok = sum(1 for r in rows if r.get("fallback_valid"))
        fail = len(rows) - ok
        restored = 0
    total = len(rows)
    coverage = round(ok / total * 100) if total else 0
    grade = "protected" if coverage >= 90 and fail == 0 else ("partial" if coverage >= 70 else "risk")
    payload = {
        "updated_at": now_iso(),
        "policy": "phase6_fallback_protection_v1",
        "mode": mode,
        "summary": {
            "total_files": total,
            "protected_count": ok,
            "issue_count": fail,
            "restored_count": restored,
            "coverage_rate": coverage,
            "grade": grade,
            "label": {"protected": "보호", "partial": "부분보호", "risk": "위험"}.get(grade, grade),
        },
        "items": rows,
        "notice": "자동 업데이트 실패 또는 JSON 손상 시 마지막 정상 스냅샷으로 복원하기 위한 보호 리포트입니다.",
    }
    write_json(ADMIN / "fallback_status.json", payload)
    write_json(ANALYSIS / "fallback_status.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["snapshot", "restore", "verify"], help="fallback protection mode")
    args = parser.parse_args()
    if args.mode == "snapshot":
        payload = snapshot()
    elif args.mode == "restore":
        payload = restore()
    else:
        payload = verify()
    print(json.dumps(payload.get("summary", {}), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

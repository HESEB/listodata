#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a safe preflight status before KOSIS_API_KEY registration and execution."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
GUIDE = DATA / "config" / "kosis_preflight_guide.json"
PHASE9 = DATA / "admin" / "phase9_readiness.json"
ADMIN_OUT = DATA / "admin" / "kosis_preflight_status.json"
ANALYSIS_OUT = DATA / "analysis" / "kosis_preflight_status.json"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    guide = read_json(GUIDE, {})
    phase9 = read_json(PHASE9, {"summary": {}, "checks": []})
    secret_name = str(guide.get("secret_name") or "KOSIS_API_KEY")
    secret_configured = bool(os.environ.get(secret_name, "").strip())

    file_checks = []
    for relative in guide.get("required_repository_files", []) or []:
        path = ROOT / str(relative)
        file_checks.append({"path": str(relative), "exists": path.is_file()})
    repository_ready = bool(file_checks) and all(x["exists"] for x in file_checks)

    phase9_status = str((phase9.get("summary") or {}).get("status") or "unknown")
    research_check = next((x for x in phase9.get("checks", []) or [] if x.get("id") == "phase9_1_3_research"), {})
    workflow_ready = (ROOT / ".github/workflows/update-market-data.yml").is_file()

    if not repository_ready or not workflow_ready:
        status = "repository_fix_required"
        next_action = "누락된 저장소 파일 또는 Workflow 연결을 복구하세요."
    elif not secret_configured:
        status = "secret_registration_required"
        next_action = "GitHub Actions Secret에 KOSIS_API_KEY를 등록한 뒤 Update market data를 수동 실행하세요."
    elif str(research_check.get("status") or "") == "credential_required":
        status = "workflow_run_required"
        next_action = "Secret은 주입됐지만 조사 결과가 갱신되지 않았습니다. Update market data를 실행하세요."
    elif research_check.get("passed"):
        status = "research_started"
        next_action = "통계목록·상세코드 후보를 검토하고 10개 지표 승인 절차를 진행하세요."
    else:
        status = "execution_review_required"
        next_action = "KOSIS 조사 화면에서 API 오류와 후보 생성 결과를 확인하세요."

    payload = {
        "updated_at": now_iso(),
        "policy": "phase10_kosis_preflight_v1",
        "summary": {
            "status": status,
            "secret_name": secret_name,
            "secret_configured": secret_configured,
            "repository_ready": repository_ready,
            "workflow_ready": workflow_ready,
            "required_file_count": len(file_checks),
            "present_file_count": sum(1 for x in file_checks if x["exists"]),
            "phase9_status": phase9_status,
            "api_key_exposed": False,
        },
        "file_checks": file_checks,
        "phase9_research": {
            "passed": bool(research_check.get("passed")),
            "status": research_check.get("status"),
            "next_action": research_check.get("next_action"),
        },
        "next_action": next_action,
        "links": guide.get("links") or {},
        "security": guide.get("security") or {},
        "notice": guide.get("notice"),
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

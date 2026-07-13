#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate official API Secret presence and safe URL shape without exposing values."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
GUIDE = DATA / "config" / "official_api_setup_guide.json"
ADMIN_OUT = DATA / "admin" / "official_api_setup_status.json"
ANALYSIS_OUT = DATA / "analysis" / "official_api_setup_status.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def masked_endpoint(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = urlparse(value)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path[:80]}"
    except Exception:
        return None


def validate_secret(spec: dict) -> dict:
    name = str(spec.get("name") or "")
    value = os.environ.get(name, "").strip()
    row = {
        "name": name,
        "provider": spec.get("provider"),
        "purpose": spec.get("purpose"),
        "configured": bool(value),
        "status": "credential_required",
        "masked_endpoint": None,
        "issues": [],
        "checks": {},
    }
    if not value:
        row["issues"].append("GitHub Actions Secret 미등록")
        return row

    try:
        parsed = urlparse(value)
        query = parse_qs(parsed.query, keep_blank_values=True)
    except Exception:
        row["status"] = "invalid_url"
        row["issues"].append("URL 파싱 실패")
        return row

    row["masked_endpoint"] = masked_endpoint(value)
    https_ok = parsed.scheme.lower() == "https"
    host = parsed.netloc.lower()
    required_hosts = [str(x).lower() for x in spec.get("required_host_contains", [])]
    host_ok = not required_hosts or any(x in host for x in required_hosts)
    required_keys = [str(x) for x in spec.get("required_query_keys", [])]
    required_keys_ok = all(k in query and any(str(v).strip() for v in query[k]) for k in required_keys)
    any_keys = [str(x) for x in spec.get("required_query_keys_any", [])]
    any_keys_ok = True if not any_keys else any(k in query and any(str(v).strip() for v in query[k]) for k in any_keys)
    recommended = [str(x) for x in spec.get("recommended_query_keys", [])]
    recommended_present = [k for k in recommended if k in query]

    row["checks"] = {
        "https": https_ok,
        "official_host": host_ok,
        "required_query_keys": required_keys_ok,
        "required_query_key_any": any_keys_ok,
        "recommended_query_keys_present": recommended_present,
    }
    if not https_ok:
        row["issues"].append("HTTPS URL이 아님")
    if not host_ok:
        row["issues"].append("공식기관 호스트 확인 실패")
    if not required_keys_ok:
        row["issues"].append("필수 KOSIS 파라미터 누락")
    if not any_keys_ok:
        row["issues"].append("서비스키 파라미터 누락")

    row["status"] = "ready" if not row["issues"] else "invalid_url"
    return row


def main() -> int:
    guide = read_json(GUIDE, {"secrets": []})
    results = [validate_secret(x) for x in guide.get("secrets", []) if isinstance(x, dict)]
    ready_count = sum(1 for x in results if x["status"] == "ready")
    missing_count = sum(1 for x in results if x["status"] == "credential_required")
    invalid_count = sum(1 for x in results if x["status"] == "invalid_url")
    if invalid_count:
        status = "invalid"
    elif ready_count == len(results) and results:
        status = "ready"
    elif ready_count:
        status = "partial"
    else:
        status = "credential_required"

    payload = {
        "updated_at": now_iso(),
        "policy": "phase8_official_api_setup_v1",
        "summary": {
            "status": status,
            "secret_count": len(results),
            "ready_count": ready_count,
            "credential_required_count": missing_count,
            "invalid_count": invalid_count,
        },
        "secrets": results,
        "security": {
            "secret_values_exposed": False,
            "display_policy": "호스트와 경로만 마스킹 표시",
        },
        "guide": "docs/phase-8-2-official-api-setup.md",
        "notice": "이 검증은 Secret 존재 여부와 기본 URL 형식만 확인하며 실제 데이터 응답 성공은 실제 공식데이터 연결 화면에서 확인합니다.",
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

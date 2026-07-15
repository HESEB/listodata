#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preserve the current approved KOSIS mapping before regeneration."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
SOURCE = DATA / "config" / "kosis_table_mapping_approved.json"
OUT = DATA / "admin" / "kosis_table_mapping_approved_previous.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    try:
        current = json.loads(SOURCE.read_text(encoding="utf-8"))
    except Exception:
        current = {"tables": [], "generation_summary": {}}
    payload = {
        "preserved_at": now_iso(),
        "source_path": str(SOURCE.relative_to(ROOT)),
        "source_updated_at": current.get("updated_at"),
        "mapping": current,
        "notice": "승인 매핑 재생성 직전 상태를 비교용으로 보관했습니다."
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"preserved": True, "table_count": len(current.get("tables", []) or [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

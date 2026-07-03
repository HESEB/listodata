#!/usr/bin/env python3
"""Collect public livestock market source snapshots.

Current version is a safe adapter scaffold.
It does not scrape dynamic government pages blindly. Instead, it:
1. reads app/data/source_registry.json,
2. writes source fetch/status metadata,
3. preserves the current manual/sample time series,
4. prepares a stable interface for future source-specific adapters.

Future adapters can replace the sample series with official CSV/Excel/API results.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "app" / "data" / "source_registry.json"
SERIES = ROOT / "app" / "data" / "source_snapshots" / "market_series_sample.json"
STATUS = ROOT / "app" / "data" / "source_snapshots" / "fetch_status.json"
KST = timezone(timedelta(hours=9))


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_status(registry: Dict[str, Any], series: Dict[str, Any]) -> Dict[str, Any]:
    series_species = {row.get("id") for row in series.get("series", [])}
    rows: List[Dict[str, Any]] = []
    for source in registry.get("sources", []):
        species = source.get("species", [])
        connected = any(sp in series_species for sp in species)
        rows.append(
            {
                "source_id": source.get("id"),
                "name": source.get("name"),
                "provider": source.get("provider"),
                "category": source.get("category"),
                "species": species,
                "target_metric": source.get("target_metric"),
                "collection_method": source.get("collection_method"),
                "status": "manual_snapshot_connected" if connected else source.get("status", "adapter_required"),
                "last_checked_at": now_kst(),
                "url": source.get("url"),
                "memo": "현재는 샘플/수동 스냅샷과 연결된 상태입니다. 공식 자동수집 어댑터는 다음 단계에서 구현합니다." if connected else source.get("memo", "")
            }
        )
    return {
        "updated_at": now_kst(),
        "notice": "공식 출처별 수집 상태 파일입니다. 현재는 수동 스냅샷 연결 여부와 향후 어댑터 필요 상태를 표시합니다.",
        "sources": rows,
    }


def main() -> None:
    registry = load_json(REGISTRY)
    series = load_json(SERIES)
    status = build_status(registry, series)
    write_json(STATUS, status)
    print(f"wrote {STATUS.relative_to(ROOT)} with {len(status['sources'])} sources")


if __name__ == "__main__":
    main()

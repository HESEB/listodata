#!/usr/bin/env python3
"""Collect public livestock market source snapshots.

Current version runs safe source adapters and records fetch status.
Adapters never overwrite production metrics directly; they create audited snapshots
that the metrics build step may use later after validation.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

from adapters.chicken_price_adapter import collect as collect_chicken_price, write_snapshot as write_chicken_snapshot

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "app" / "data" / "source_registry.json"
SERIES = ROOT / "app" / "data" / "source_snapshots" / "market_series_sample.json"
STATUS = ROOT / "app" / "data" / "source_snapshots" / "fetch_status.json"
CHICKEN_SNAPSHOT = ROOT / "app" / "data" / "source_snapshots" / "chicken_price_snapshot.json"
KST = timezone(timedelta(hours=9))


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_adapter(source: Dict[str, Any]) -> Dict[str, Any] | None:
    source_id = source.get("id")
    if source_id == "CHICKEN_PRICE_9_10":
        snapshot = collect_chicken_price(source)
        write_chicken_snapshot(CHICKEN_SNAPSHOT, snapshot)
        snap = asdict(snapshot)
        return {
            "adapter_status": snapshot.status,
            "adapter_message": snapshot.message,
            "snapshot_file": "app/data/source_snapshots/chicken_price_snapshot.json",
            "latest_label": snap.get("latest_label"),
            "latest_value": snap.get("latest_value"),
        }
    return None


def build_status(registry: Dict[str, Any], series: Dict[str, Any]) -> Dict[str, Any]:
    series_species = {row.get("id") for row in series.get("series", [])}
    rows: List[Dict[str, Any]] = []
    for source in registry.get("sources", []):
        species = source.get("species", [])
        connected = any(sp in series_species for sp in species)
        adapter_result = run_adapter(source)
        status = source.get("status", "adapter_required")
        memo = source.get("memo", "")
        if adapter_result:
            status = adapter_result["adapter_status"]
            memo = adapter_result["adapter_message"]
        elif connected:
            status = "manual_snapshot_connected"
            memo = "현재는 샘플/수동 스냅샷과 연결된 상태입니다. 공식 자동수집 어댑터는 다음 단계에서 구현합니다."

        row = {
            "source_id": source.get("id"),
            "name": source.get("name"),
            "provider": source.get("provider"),
            "category": source.get("category"),
            "species": species,
            "target_metric": source.get("target_metric"),
            "collection_method": source.get("collection_method"),
            "status": status,
            "last_checked_at": now_kst(),
            "url": source.get("url"),
            "memo": memo,
        }
        if adapter_result:
            row.update({k: v for k, v in adapter_result.items() if k not in {"adapter_status", "adapter_message"}})
        rows.append(row)

    return {
        "updated_at": now_kst(),
        "notice": "공식 출처별 수집 상태 파일입니다. 일부 출처는 실제 어댑터를 실행하고, 나머지는 수동 스냅샷 연결 또는 어댑터 필요 상태로 표시합니다.",
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Snapshot KOSIS official data before single-key runtime collection.

The snapshot is temporary workflow state under .runtime and is never committed.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app" / "data" / "official" / "manual" / "real_source_metrics.json"
BACKUP = ROOT / ".runtime" / "kosis" / "real_source_metrics.before.json"


def main() -> int:
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    if SOURCE.exists():
        shutil.copy2(SOURCE, BACKUP)
        print(f"snapshot_created={BACKUP.relative_to(ROOT)}")
    else:
        BACKUP.write_text('{"updated_at":null,"records":[]}\n', encoding="utf-8")
        print("snapshot_created=empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
HESEB Version Engine
- Generates app/data/system/version.json on every data refresh.
- Keeps UI version, build time, workflow metadata, and data update timestamps in one place.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_DIR = ROOT / "app" / "data" / "system"
SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
VERSION_PATH = SYSTEM_DIR / "version.json"
UPDATE_STATUS_PATH = ROOT / "app" / "data" / "update_status.json"
CHANGE_LOG_PATH = ROOT / "app" / "data" / "admin" / "change_log.json"

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def iso_kst(dt: datetime) -> str:
    return dt.astimezone(KST).replace(microsecond=0).isoformat()


def git_output(args: list[str], default: str = "") -> str:
    try:
        return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return default


def read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def count_items(path: Path) -> int:
    data = read_json(path, None)
    if data is None:
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("items", "events", "news", "data", "records"):
            if isinstance(data.get(key), list):
                return len(data[key])
        return len(data)
    return 0


def existing_patch() -> int:
    old = read_json(VERSION_PATH, {})
    v = str(old.get("version", "v6.2.0"))
    try:
        return int(v.split(".")[-1])
    except Exception:
        return 0


def build_version() -> dict:
    dt = now_kst()
    commit = git_output(["git", "rev-parse", "--short", "HEAD"], "unknown")
    branch = git_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], os.getenv("GITHUB_REF_NAME", "unknown"))
    workflow = os.getenv("GITHUB_WORKFLOW", "local/manual")
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    actor = os.getenv("GITHUB_ACTOR", "local")

    update_status = read_json(UPDATE_STATUS_PATH, {})
    change_log = read_json(CHANGE_LOG_PATH, {})

    # Phase based semantic version: Phase 6.2 + monotonically updated build date.
    version = "v6.2.0"

    files = {
        "market_dashboard": ROOT / "app" / "data" / "market_dashboard.json",
        "events_news": ROOT / "app" / "data" / "events" / "events_news.json",
        "events_official": ROOT / "app" / "data" / "events" / "events_official.json",
        "evidence_scores": ROOT / "app" / "data" / "analysis" / "evidence_scores.json",
        "evidence_chains": ROOT / "app" / "data" / "analysis" / "evidence_chains.json",
        "quality_report": ROOT / "app" / "data" / "admin" / "quality_report.json",
        "change_log": CHANGE_LOG_PATH,
    }

    data_counts = {name: count_items(path) for name, path in files.items()}
    data_updated = (
        update_status.get("updated_at")
        or update_status.get("generated_at")
        or change_log.get("generated_at")
        or iso_kst(dt)
    )

    return {
        "schema_version": "version-engine-v1",
        "version": version,
        "phase": "Phase 6-2",
        "title": "Version Engine 구축",
        "build_time_kst": iso_kst(dt),
        "data_updated_at": data_updated,
        "workflow": {
            "name": workflow,
            "status": "success",
            "run_id": run_id,
            "run_attempt": run_attempt,
            "actor": actor,
            "branch": branch,
            "commit": commit,
        },
        "cache_bust": f"{dt.strftime('%Y%m%d%H%M%S')}-{commit}",
        "data_counts": data_counts,
        "display": {
            "label": f"{version} · {dt.strftime('%m/%d %H:%M')} KST",
            "short_label": version,
            "build_label": f"Build {dt.strftime('%Y-%m-%d %H:%M')} KST",
            "data_label": f"Data {data_updated}",
            "status_label": "Actions 정상",
        },
        "notes": [
            "메인 노출 버전은 app/data/system/version.json 기준으로 표시됩니다.",
            "코드 버전과 데이터 갱신 시간을 분리 표시합니다.",
            "브라우저 캐시를 우회하기 위해 cache_bust 값을 함께 제공합니다.",
        ],
    }


def main() -> None:
    data = build_version()
    VERSION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Version info written: {VERSION_PATH}")


if __name__ == "__main__":
    main()

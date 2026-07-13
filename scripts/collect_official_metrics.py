#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect and normalize official livestock metrics for DSS 2.0.

Phase 7-2 principles:
- Never invent metric values.
- Accept only configured local JSON, remote JSON, or remote CSV inputs.
- Preserve existing snapshot/history when no valid new records are collected.
- Produce source-level collection status for Admin and Analysis.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CONFIG = DATA / "config" / "official_source_registry.json"
CATALOG = DATA / "design" / "official_data_catalog.json"
RAW = DATA / "official" / "raw" / "official_metrics_raw.json"
CLEAN = DATA / "official" / "clean" / "official_metrics_clean.json"
SNAPSHOT = DATA / "official" / "snapshot" / "official_metrics_snapshot.json"
HISTORY = DATA / "official" / "history" / "official_metrics_history.json"
ADMIN_STATUS = DATA / "admin" / "official_data_collection.json"
ANALYSIS_STATUS = DATA / "analysis" / "official_data_collection.json"
USER_AGENT = "HESEB-Livestock-Terminal/2.0 (+https://heseb.github.io/listodata/)"
VALID_SPECIES = {"BEEF", "PORK", "POULTRY", "EGG", "DUCK", "OTHER"}
VALID_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "yearly", "event"}


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


def fetch_bytes(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def nested_get(data: Any, path: str) -> Any:
    if not path:
        return data
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def as_records(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for key in ("records", "items", "data", "rows"):
            if isinstance(value.get(key), list):
                return [x for x in value[key] if isinstance(x, dict)]
        return [value]
    return []


def parse_source(source: dict, defaults: dict) -> tuple[list[dict], str]:
    adapter = source.get("adapter")
    timeout = int(source.get("timeout_seconds") or defaults.get("timeout_seconds") or 30)
    if adapter == "local_json":
        path = ROOT / str(source.get("path") or "")
        if not path.exists():
            raise FileNotFoundError(str(path))
        payload = read_json(path, {})
        return as_records(nested_get(payload, str(source.get("record_path") or "records"))), str(path.relative_to(ROOT))

    url = str(source.get("url") or "").strip()
    env_name = str(source.get("url_env") or "").strip()
    if not url and env_name:
        url = os.environ.get(env_name, "").strip()
    if not url:
        raise RuntimeError(f"endpoint missing: {env_name or source.get('source_id')}")

    raw = fetch_bytes(url, timeout)
    if adapter == "remote_json":
        payload = json.loads(raw.decode("utf-8-sig"))
        return as_records(nested_get(payload, str(source.get("record_path") or ""))), url
    if adapter == "remote_csv":
        text = raw.decode(source.get("encoding") or "utf-8-sig")
        return list(csv.DictReader(io.StringIO(text))), url
    raise RuntimeError(f"unsupported adapter: {adapter}")


def catalog_index() -> dict[str, dict]:
    catalog = read_json(CATALOG, {})
    out: dict[str, dict] = {}
    for species, meta in (catalog.get("species") or {}).items():
        for metric in meta.get("required_metrics", []) or []:
            row = dict(metric)
            row["species"] = species
            out[str(metric.get("metric_id"))] = row
    return out


def first_value(row: dict, *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def to_number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).replace(",", "").strip()
    try:
        num = float(text)
        return int(num) if num.is_integer() else num
    except Exception:
        return None


def normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(".", "-").replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 6 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}"
    return text[:10]


def record_id(metric_id: str, date: str, provider: str, value: Any) -> str:
    key = f"{metric_id}|{date}|{provider}|{value}"
    return "OFFMET_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]


def comparison(row: dict, prefix: str) -> dict | None:
    base = to_number(first_value(row, f"{prefix}_base_value", f"comparison_{prefix}_base_value"))
    change = to_number(first_value(row, f"{prefix}_change", f"comparison_{prefix}_change"))
    rate = to_number(first_value(row, f"{prefix}_change_rate", f"comparison_{prefix}_change_rate"))
    base_date = normalize_date(first_value(row, f"{prefix}_base_date", f"comparison_{prefix}_base_date"))
    if base is None and change is None and rate is None:
        return None
    return {"base_value": base, "change": change, "change_rate": rate, "base_date": base_date}


def normalize_record(row: dict, source: dict, endpoint: str, catalog: dict[str, dict]) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    metric_id = str(first_value(row, "metric_id", "metricId", "METRIC_ID") or "").strip().upper()
    meta = catalog.get(metric_id)
    species = str(first_value(row, "species", "species_code", "SPECIES") or (meta or {}).get("species") or "").strip().upper()
    category = str(first_value(row, "category", "CATEGORY") or (meta or {}).get("category") or "").strip().lower()
    frequency = str(first_value(row, "frequency", "period_frequency", "FREQUENCY") or (meta or {}).get("frequency") or "").strip().lower()
    date = normalize_date(first_value(row, "date", "period_date", "base_date", "DATE"))
    value = to_number(first_value(row, "value", "metric_value", "VALUE"))
    unit = str(first_value(row, "unit", "UNIT") or "").strip()
    provider = str(first_value(row, "provider", "source_provider") or source.get("provider") or "").strip()
    dataset = first_value(row, "dataset", "source_dataset") or source.get("dataset")
    url = first_value(row, "url", "source_url") or endpoint
    published_at = first_value(row, "published_at", "source_published_at")

    if not metric_id:
        errors.append("metric_id missing")
    elif metric_id not in catalog:
        errors.append("metric_id not in catalog")
    if species not in VALID_SPECIES:
        errors.append("invalid species")
    if not category:
        errors.append("category missing")
    if frequency not in VALID_FREQUENCIES:
        errors.append("invalid frequency")
    if not date:
        errors.append("date missing")
    if value is None:
        errors.append("value missing or non-numeric")
    if not unit:
        errors.append("unit missing")
    if not provider:
        errors.append("provider missing")
    if not url:
        errors.append("source url missing")

    comparisons = {}
    for key in ("day", "week", "month", "quarter", "year"):
        comp = comparison(row, key)
        if comp:
            comparisons[key] = comp

    if errors:
        return None, errors

    retrieved_at = now_iso()
    normalized = {
        "record_id": str(first_value(row, "record_id") or record_id(metric_id, date or "", provider, value)),
        "metric_id": metric_id,
        "species": species,
        "category": category,
        "period": {"date": date, "frequency": frequency, "timezone": "Asia/Seoul"},
        "value": value,
        "unit": unit,
        "comparisons": comparisons,
        "source": {
            "provider": provider,
            "dataset": dataset,
            "url": url,
            "source_level": int(source.get("source_level") or 5),
            "retrieved_at": retrieved_at,
            "published_at": published_at,
        },
        "quality": {
            "status": "valid",
            "freshness_score": float(first_value(row, "freshness_score") or 100),
            "reliability_score": float(first_value(row, "reliability_score") or source.get("reliability_score") or 90),
            "validation_errors": [],
        },
        "metadata": {
            "source_id": source.get("source_id"),
            "metric_name": (meta or {}).get("name"),
            "priority": (meta or {}).get("priority"),
            "collector_policy": "phase7_official_collector_v1",
        },
    }
    return normalized, []


def latest_records(records: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for row in records:
        metric_id = row.get("metric_id")
        date = ((row.get("period") or {}).get("date") or "")
        prev = latest.get(metric_id)
        prev_date = (((prev or {}).get("period") or {}).get("date") or "")
        if prev is None or date >= prev_date:
            latest[metric_id] = row
    return sorted(latest.values(), key=lambda x: (x.get("species", ""), x.get("metric_id", "")))


def merge_history(existing: list[dict], incoming: list[dict], limit: int = 5000) -> list[dict]:
    merged: dict[str, dict] = {}
    for row in existing + incoming:
        key = str(row.get("record_id") or "")
        if key:
            merged[key] = row
    rows = sorted(merged.values(), key=lambda x: (((x.get("period") or {}).get("date") or ""), x.get("metric_id", "")))
    return rows[-limit:]


def main() -> int:
    registry = read_json(CONFIG, {})
    defaults = registry.get("defaults") or {}
    catalog = catalog_index()
    source_results = []
    raw_records = []
    clean_records = []
    rejected = []

    for source in registry.get("sources", []) or []:
        result = {
            "source_id": source.get("source_id"),
            "provider": source.get("provider"),
            "adapter": source.get("adapter"),
            "enabled": bool(source.get("enabled", defaults.get("enabled", False))),
            "status": "disabled",
            "fetched_count": 0,
            "valid_count": 0,
            "rejected_count": 0,
            "message": source.get("note") or "",
        }
        if not result["enabled"]:
            source_results.append(result)
            continue
        try:
            rows, endpoint = parse_source(source, defaults)
            result["fetched_count"] = len(rows)
            result["status"] = "success"
            for row in rows:
                raw_records.append({"source_id": source.get("source_id"), "retrieved_at": now_iso(), "payload": row})
                normalized, errors = normalize_record(row, source, endpoint, catalog)
                if normalized:
                    clean_records.append(normalized)
                    result["valid_count"] += 1
                else:
                    rejected.append({"source_id": source.get("source_id"), "payload": row, "errors": errors})
                    result["rejected_count"] += 1
            if not rows:
                result["status"] = "empty"
                result["message"] = "수집 대상 레코드 없음"
        except Exception as exc:
            result["status"] = "failed"
            result["message"] = str(exc)[:300]
            print(f"WARN: official source failed: {source.get('source_id')}: {exc}", file=sys.stderr)
        source_results.append(result)

    generated_at = now_iso()
    write_json(RAW, {
        "updated_at": generated_at,
        "policy": "phase7_official_raw_v2",
        "layer": "raw",
        "notice": "공식 데이터 소스에서 이번 실행에 수집한 원본 레코드입니다.",
        "records": raw_records,
    })

    if clean_records:
        write_json(CLEAN, {
            "updated_at": generated_at,
            "policy": "phase7_official_clean_v2",
            "layer": "clean",
            "notice": "카탈로그 및 필수 필드 검증을 통과한 공식 데이터입니다.",
            "records": clean_records,
            "rejected": rejected,
        })
        snapshot_records = latest_records(clean_records)
        write_json(SNAPSHOT, {
            "updated_at": generated_at,
            "policy": "phase7_official_snapshot_v2",
            "layer": "snapshot",
            "notice": "Dashboard와 DSS 엔진이 사용하는 지표별 최신 공식 데이터입니다.",
            "records": snapshot_records,
        })
        old_history_doc = read_json(HISTORY, {"records": []})
        history_records = merge_history(old_history_doc.get("records", []) or [], clean_records)
        write_json(HISTORY, {
            "updated_at": generated_at,
            "policy": "phase7_official_history_v2",
            "layer": "history",
            "notice": "전일·전월·전년 비교와 추세 분석용 공식 데이터 이력입니다.",
            "records": history_records,
        })
        overall = "success"
    else:
        overall = "waiting_sources" if not any(x["status"] == "failed" for x in source_results) else "warning"

    status = {
        "updated_at": generated_at,
        "policy": "phase7_official_collection_status_v1",
        "summary": {
            "status": overall,
            "configured_source_count": len(source_results),
            "enabled_source_count": sum(1 for x in source_results if x["enabled"]),
            "successful_source_count": sum(1 for x in source_results if x["status"] in {"success", "empty"}),
            "failed_source_count": sum(1 for x in source_results if x["status"] == "failed"),
            "raw_count": len(raw_records),
            "valid_count": len(clean_records),
            "rejected_count": len(rejected),
            "snapshot_preserved": not bool(clean_records),
        },
        "sources": source_results,
        "rejected": rejected[:100],
        "notice": "신규 유효 데이터가 0건이면 기존 Clean/Snapshot/History를 보존합니다."
    }
    write_json(ADMIN_STATUS, status)
    write_json(ANALYSIS_STATUS, status)
    print(json.dumps(status["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

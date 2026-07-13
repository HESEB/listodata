#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect real official livestock data from configured KOSIS/data.go.kr URLs.

The complete API URLs, including credentials and table parameters, are injected
through GitHub Actions Secrets. Missing credentials are reported as
credential_required and do not erase existing approved data.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CONFIG = DATA / "config" / "real_official_source_connections.json"
OUTPUT = DATA / "official" / "manual" / "real_source_metrics.json"
ADMIN_STATUS = DATA / "admin" / "real_official_source_connections.json"
ANALYSIS_STATUS = DATA / "analysis" / "real_official_source_connections.json"
USER_AGENT = "HESEB-Livestock-Terminal/2.0 (+https://heseb.github.io/listodata/)"


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


def fetch_json(url: str, timeout: int = 35) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8-sig"))


def nested_get(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if not part:
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def as_records(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def first(row: dict, keys: list[str]) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def normalize_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(".", "-").replace("/", "-")
    if text.isdigit() and len(text) == 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if text.isdigit() and len(text) == 6:
        return f"{text[:4]}-{text[4:6]}"
    if text.isdigit() and len(text) == 4:
        return text
    return text[:10]


def to_number(value: Any) -> float | int | None:
    if value in (None, "", "-"):
        return None
    text = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    if not text:
        return None
    try:
        number = float(text)
        return int(number) if number.is_integer() else number
    except Exception:
        return None


def choose_metric(text: str, rules: list[dict]) -> dict | None:
    low = text.lower()
    candidates = []
    for rule in rules:
        hits = sum(1 for word in rule.get("keywords", []) if str(word).lower() in low)
        if hits:
            candidates.append((hits, rule))
    return max(candidates, key=lambda x: x[0])[1] if candidates else None


def kosis_records(payload: Any, source: dict, endpoint: str) -> list[dict]:
    rows = as_records(payload)
    out = []
    for row in rows:
        context = " ".join(str(row.get(k) or "") for k in ("TBL_NM", "ITM_NM", "C1_NM", "C2_NM", "C3_NM"))
        rule = choose_metric(context, source.get("metric_rules", []))
        value = to_number(row.get("DT"))
        date = normalize_date(row.get("PRD_DE"))
        unit = str(row.get("UNIT_NM") or "").strip()
        if not rule or value is None or not date or not unit:
            continue
        out.append({
            "metric_id": rule["metric_id"],
            "species": rule["species"],
            "category": source.get("category"),
            "frequency": source.get("frequency"),
            "date": date,
            "value": value,
            "unit": unit,
            "provider": source.get("provider"),
            "dataset": row.get("TBL_NM") or source.get("dataset"),
            "url": endpoint,
            "published_at": row.get("LST_CHN_DE"),
            "reliability_score": source.get("reliability_score", 98)
        })
    return out


def data_go_records(payload: Any, source: dict, endpoint: str) -> list[dict]:
    rows: list[dict] = []
    for path in source.get("record_paths", []):
        found = nested_get(payload, path)
        rows = as_records(found)
        if rows:
            break
    field_map = source.get("field_map", {})
    out = []
    for row in rows:
        metric_id = first(row, field_map.get("metric_id", []))
        species = first(row, field_map.get("species", []))
        category = first(row, field_map.get("category", []))
        date = normalize_date(first(row, field_map.get("date", [])))
        value = to_number(first(row, field_map.get("value", [])))
        unit = first(row, field_map.get("unit", []))
        if not all([metric_id, species, category, date, unit]) or value is None:
            continue
        out.append({
            "metric_id": str(metric_id).upper(),
            "species": str(species).upper(),
            "category": str(category).lower(),
            "frequency": row.get("frequency") or "daily",
            "date": date,
            "value": value,
            "unit": str(unit),
            "provider": source.get("provider"),
            "dataset": source.get("dataset"),
            "url": endpoint,
            "reliability_score": source.get("reliability_score", 98)
        })
    return out


def main() -> int:
    config = read_json(CONFIG, {"sources": []})
    existing = read_json(OUTPUT, {"records": []})
    collected: list[dict] = []
    results = []

    for source in config.get("sources", []):
        result = {
            "source_id": source.get("source_id"),
            "provider": source.get("provider"),
            "dataset": source.get("dataset"),
            "status": "disabled",
            "record_count": 0,
            "url_env": source.get("url_env"),
            "official_page": source.get("official_page"),
            "message": ""
        }
        if not source.get("enabled", True):
            results.append(result)
            continue
        env_name = str(source.get("url_env") or "")
        url = os.environ.get(env_name, "").strip()
        if not url:
            result["status"] = "credential_required"
            result["message"] = f"GitHub Actions Secret {env_name} 설정 필요"
            results.append(result)
            continue
        try:
            payload = fetch_json(url)
            adapter = source.get("adapter")
            if adapter == "kosis_json":
                rows = kosis_records(payload, source, url)
            elif adapter == "data_go_json":
                rows = data_go_records(payload, source, url)
            else:
                raise RuntimeError(f"unsupported adapter: {adapter}")
            collected.extend(rows)
            result["record_count"] = len(rows)
            result["status"] = "success" if rows else "empty"
            result["message"] = "공식 데이터 수집 성공" if rows else "응답은 정상이나 매핑 가능한 레코드 없음"
        except Exception as exc:
            result["status"] = "failed"
            result["message"] = str(exc)[:300]
        results.append(result)

    if collected:
        payload = {
            "updated_at": now_iso(),
            "policy": "phase8_real_official_sources_v1",
            "records": collected,
            "notice": "실제 공식기관 API에서 수집한 데이터입니다."
        }
        write_json(OUTPUT, payload)
        preserved = False
    else:
        preserved = bool(existing.get("records"))
        if not OUTPUT.exists():
            write_json(OUTPUT, {"updated_at": None, "policy": "phase8_real_official_sources_v1", "records": [], "notice": "공식 API 인증정보 설정 전 초기 상태"})

    success_count = sum(1 for x in results if x["status"] == "success")
    credential_count = sum(1 for x in results if x["status"] == "credential_required")
    failed_count = sum(1 for x in results if x["status"] == "failed")
    status = "ready" if success_count else ("credential_required" if credential_count and not failed_count else "limited")
    status_payload = {
        "updated_at": now_iso(),
        "policy": "phase8_real_official_sources_v1",
        "summary": {
            "status": status,
            "source_count": len(results),
            "success_count": success_count,
            "credential_required_count": credential_count,
            "failed_count": failed_count,
            "collected_record_count": len(collected),
            "previous_data_preserved": preserved
        },
        "sources": results,
        "output": str(OUTPUT.relative_to(ROOT)),
        "notice": config.get("notice")
    }
    write_json(ADMIN_STATUS, status_payload)
    write_json(ANALYSIS_STATUS, status_payload)
    print(json.dumps(status_payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

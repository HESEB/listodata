#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect real official livestock data.

Promoted KOSIS operational mappings are preferred and runtime URLs are built in
memory from KOSIS_API_KEY. Before promotion, legacy full-URL Secrets remain the
safe fallback. Credentials and generated URLs are never persisted.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kosis_mapping_runtime import build_kosis_url, resolve_mapping, table_index

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CONFIG = DATA / "config" / "real_official_source_connections.json"
OUTPUT = DATA / "official" / "manual" / "real_source_metrics.json"
ADMIN_STATUS = DATA / "admin" / "real_official_source_connections.json"
ANALYSIS_STATUS = DATA / "analysis" / "real_official_source_connections.json"
RUNTIME_STATUS = DATA / "admin" / "kosis_runtime_mapping_status.json"
RUNTIME_ANALYSIS = DATA / "analysis" / "kosis_runtime_mapping_status.json"
USER_AGENT = "HESEB-Livestock-Terminal/3.0 (+https://heseb.github.io/listodata/)"


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


def exact_metric_index(table: dict | None) -> dict[tuple[str, str], dict]:
    index: dict[tuple[str, str], dict] = {}
    if not table:
        return index
    for mapping in table.get("metric_mappings", []) or []:
        if not isinstance(mapping, dict) or not mapping.get("enabled", True):
            continue
        item_id = str((mapping.get("item_selector") or {}).get("ITM_ID") or "")
        class_id = str((mapping.get("classification_selectors") or {}).get("C1_ID") or "")
        if item_id and class_id:
            index[(item_id, class_id)] = mapping
    return index


def kosis_records(payload: Any, source: dict, table: dict | None) -> list[dict]:
    rows = as_records(payload)
    out = []
    exact = exact_metric_index(table)
    for row in rows:
        item_id = str(row.get("ITM_ID") or "")
        class_id = str(row.get("C1_ID") or "")
        mapping = exact.get((item_id, class_id))
        if mapping:
            rule = {"metric_id": mapping.get("metric_id"), "species": mapping.get("species")}
            mapping_mode = "operational_code_match"
        else:
            context = " ".join(str(row.get(k) or "") for k in ("TBL_NM", "ITM_NM", "C1_NM", "C2_NM", "C3_NM"))
            rule = choose_metric(context, source.get("metric_rules", []))
            mapping_mode = "legacy_keyword_match"
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
            "source_id": source.get("source_id"),
            "published_at": row.get("LST_CHN_DE"),
            "reliability_score": source.get("reliability_score", 98),
            "mapping_mode": mapping_mode,
            "ITM_ID": item_id or None,
            "C1_ID": class_id or None,
        })
    return out


def data_go_records(payload: Any, source: dict) -> list[dict]:
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
            "source_id": source.get("source_id"),
            "reliability_score": source.get("reliability_score", 98),
            "mapping_mode": "configured_field_map",
        })
    return out


def main() -> int:
    config = read_json(CONFIG, {"sources": []})
    existing = read_json(OUTPUT, {"records": []})
    mapping, runtime = resolve_mapping()
    tables = table_index(mapping)
    operational_active = runtime["mapping_source"] == "operational"
    api_key = os.environ.get("KOSIS_API_KEY", "").strip()
    collected: list[dict] = []
    results: list[dict] = []
    runtime_url_count = 0

    for source in config.get("sources", []):
        source_id = str(source.get("source_id") or "")
        adapter = source.get("adapter")
        table = tables.get(source_id) if adapter == "kosis_json" else None
        result = {
            "source_id": source_id,
            "provider": source.get("provider"),
            "dataset": source.get("dataset"),
            "status": "disabled",
            "record_count": 0,
            "url_env": source.get("url_env"),
            "official_page": source.get("official_page"),
            "mapping_source": runtime["mapping_source"] if adapter == "kosis_json" else "source_config",
            "endpoint_mode": None,
            "message": "",
        }
        if not source.get("enabled", True):
            results.append(result)
            continue

        url = ""
        build_errors: list[str] = []
        if adapter == "kosis_json" and operational_active:
            url, build_errors = build_kosis_url(table or {}, api_key)
            result["endpoint_mode"] = "operational_runtime"
            if url:
                runtime_url_count += 1
        else:
            env_name = str(source.get("url_env") or "")
            url = os.environ.get(env_name, "").strip()
            result["endpoint_mode"] = "legacy_secret_url"

        if not url:
            result["status"] = "credential_required" if any("API_KEY" in x for x in build_errors) or not operational_active else "mapping_required"
            result["message"] = "; ".join(build_errors) if build_errors else f"GitHub Actions Secret {source.get('url_env')} 설정 필요"
            results.append(result)
            continue

        try:
            payload = fetch_json(url)
            if adapter == "kosis_json":
                rows = kosis_records(payload, source, table if operational_active else None)
            elif adapter == "data_go_json":
                rows = data_go_records(payload, source)
            else:
                raise RuntimeError(f"unsupported adapter: {adapter}")
            collected.extend(rows)
            result["record_count"] = len(rows)
            result["status"] = "success" if rows else "empty"
            result["message"] = "공식 데이터 수집 성공" if rows else "응답은 정상이나 매핑 가능한 레코드 없음"
        except Exception as exc:
            result["status"] = "failed"
            result["message"] = f"{type(exc).__name__}: {str(exc)[:220]}"
        results.append(result)

    if collected:
        write_json(OUTPUT, {
            "updated_at": now_iso(),
            "policy": "phase9_real_official_sources_runtime_v1",
            "mapping_source": runtime["mapping_source"],
            "records": collected,
            "notice": "실제 공식기관 API에서 수집한 데이터입니다. 인증 URL은 저장하지 않습니다.",
        })
        preserved = False
    else:
        preserved = bool(existing.get("records"))
        if not OUTPUT.exists():
            write_json(OUTPUT, {"updated_at": None, "policy": "phase9_real_official_sources_runtime_v1", "records": [], "notice": "공식 API 인증정보 설정 전 초기 상태"})

    success_count = sum(1 for x in results if x["status"] == "success")
    credential_count = sum(1 for x in results if x["status"] == "credential_required")
    mapping_required_count = sum(1 for x in results if x["status"] == "mapping_required")
    failed_count = sum(1 for x in results if x["status"] == "failed")
    status = "ready" if success_count else ("credential_required" if credential_count and not failed_count else "limited")
    status_payload = {
        "updated_at": now_iso(),
        "policy": "phase9_real_official_sources_runtime_v1",
        "summary": {
            "status": status,
            "source_count": len(results),
            "success_count": success_count,
            "credential_required_count": credential_count,
            "mapping_required_count": mapping_required_count,
            "failed_count": failed_count,
            "collected_record_count": len(collected),
            "previous_data_preserved": preserved,
            "operational_mapping_active": operational_active,
            "runtime_url_count": runtime_url_count,
            "fallback_used": runtime["fallback_used"],
        },
        "runtime_mapping": runtime,
        "sources": results,
        "output": str(OUTPUT.relative_to(ROOT)),
        "security": {"api_key_exposed": False, "runtime_urls_persisted": False},
        "notice": "승격된 운영 매핑은 KOSIS_API_KEY와 결합해 실행 중에만 URL을 생성합니다. 미승격 상태에서는 기존 Secret URL을 사용합니다.",
    }
    write_json(ADMIN_STATUS, status_payload)
    write_json(ANALYSIS_STATUS, status_payload)
    runtime_payload = {
        "updated_at": status_payload["updated_at"],
        "policy": "phase9_kosis_runtime_mapping_v1",
        "summary": {
            "status": "active" if operational_active else "fallback",
            "mapping_source": runtime["mapping_source"],
            "promotion_status": runtime["promotion_status"],
            "runtime_url_count": runtime_url_count,
            "kosis_source_count": sum(1 for x in results if x.get("endpoint_mode") in {"operational_runtime", "legacy_secret_url"} and str(x.get("source_id", "")).startswith("KOSIS_")),
            "successful_kosis_source_count": sum(1 for x in results if str(x.get("source_id", "")).startswith("KOSIS_") and x.get("status") == "success"),
            "fallback_used": runtime["fallback_used"],
        },
        "runtime_mapping": runtime,
        "sources": [x for x in results if str(x.get("source_id", "")).startswith("KOSIS_")],
        "security": {"api_key_exposed": False, "generated_url_exposed": False},
        "notice": "운영 매핑 승격 전에는 fallback이 정상입니다.",
    }
    write_json(RUNTIME_STATUS, runtime_payload)
    write_json(RUNTIME_ANALYSIS, runtime_payload)
    print(json.dumps(status_payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

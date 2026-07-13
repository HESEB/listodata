#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate Phase 7-1 official data schema and storage layers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
CATALOG = DATA / "design" / "official_data_catalog.json"
SCHEMA = DATA / "schema" / "official_metric.schema.json"
LAYERS = {
    "raw": DATA / "official" / "raw" / "official_metrics_raw.json",
    "clean": DATA / "official" / "clean" / "official_metrics_clean.json",
    "snapshot": DATA / "official" / "snapshot" / "official_metrics_snapshot.json",
    "history": DATA / "official" / "history" / "official_metrics_history.json",
}
ADMIN_OUT = DATA / "admin" / "official_data_structure.json"
ANALYSIS_OUT = DATA / "analysis" / "official_data_structure.json"
REQUIRED_RECORD_FIELDS = ["record_id", "metric_id", "species", "category", "period", "value", "unit", "source", "quality"]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_errors(record: dict, catalog_ids: set[str]) -> list[str]:
    errors = [f"missing:{k}" for k in REQUIRED_RECORD_FIELDS if k not in record]
    metric_id = record.get("metric_id")
    if metric_id and metric_id not in catalog_ids:
        errors.append("metric_id_not_in_catalog")
    if record.get("species") not in {"BEEF", "PORK", "POULTRY", "EGG", "DUCK", "OTHER"}:
        errors.append("invalid_species")
    period = record.get("period")
    if not isinstance(period, dict) or not period.get("date") or not period.get("frequency"):
        errors.append("invalid_period")
    source = record.get("source")
    if not isinstance(source, dict) or not source.get("provider") or not source.get("retrieved_at"):
        errors.append("invalid_source")
    quality = record.get("quality")
    if not isinstance(quality, dict) or "freshness_score" not in quality or "reliability_score" not in quality:
        errors.append("invalid_quality")
    return errors


def main() -> int:
    checks = []
    catalog_ids: set[str] = set()
    species_required: dict[str, int] = {}

    try:
        catalog = read_json(CATALOG)
        for species, spec in catalog.get("species", {}).items():
            metrics = spec.get("required_metrics", [])
            species_required[species] = len(metrics)
            for metric in metrics:
                if metric.get("metric_id"):
                    catalog_ids.add(metric["metric_id"])
        checks.append({"id": "catalog", "status": "ok", "message": f"{len(catalog_ids)} metrics"})
    except Exception as exc:
        catalog = {}
        checks.append({"id": "catalog", "status": "critical", "message": str(exc)})

    try:
        schema = read_json(SCHEMA)
        required = set(schema.get("required", []))
        missing = [x for x in REQUIRED_RECORD_FIELDS if x not in required]
        checks.append({"id": "schema", "status": "ok" if not missing else "critical", "message": "required fields valid" if not missing else f"missing required: {missing}"})
    except Exception as exc:
        checks.append({"id": "schema", "status": "critical", "message": str(exc)})

    layer_summary = {}
    total_records = 0
    invalid_records = 0
    for name, path in LAYERS.items():
        try:
            doc = read_json(path)
            if name == "snapshot":
                snapshot_species = doc.get("species", {})
                missing_species = [sp for sp in species_required if sp not in snapshot_species]
                status = "ok" if not missing_species else "critical"
                message = "all species initialized" if not missing_species else f"missing species: {missing_species}"
                count = sum(len((row or {}).get("metrics", {})) for row in snapshot_species.values())
            else:
                records = doc.get("records", [])
                if not isinstance(records, list):
                    raise ValueError("records must be array")
                count = len(records)
                bad = []
                for idx, record in enumerate(records):
                    errs = record_errors(record, catalog_ids)
                    if errs:
                        bad.append({"index": idx, "errors": errs})
                invalid_records += len(bad)
                status = "ok" if not bad else "warning"
                message = f"{count} records" if not bad else f"{len(bad)} invalid records"
            total_records += count
            layer_summary[name] = {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "record_count": count, "status": status}
            checks.append({"id": f"layer_{name}", "status": status, "message": message})
        except Exception as exc:
            layer_summary[name] = {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "record_count": 0, "status": "critical"}
            checks.append({"id": f"layer_{name}", "status": "critical", "message": str(exc)})

    critical = sum(1 for x in checks if x["status"] == "critical")
    warning = sum(1 for x in checks if x["status"] == "warning")
    grade = "critical" if critical else ("warning" if warning else "ready")
    payload = {
        "updated_at": now_iso(),
        "policy": "phase7_official_data_structure_v1",
        "summary": {
            "grade": grade,
            "label": {"ready": "구조 준비완료", "warning": "검토 필요", "critical": "구조 오류"}[grade],
            "catalog_metric_count": len(catalog_ids),
            "species_count": len(species_required),
            "layer_count": len(LAYERS),
            "record_count": total_records,
            "invalid_record_count": invalid_records,
            "critical_count": critical,
            "warning_count": warning,
        },
        "species_required_metrics": species_required,
        "layers": layer_summary,
        "checks": checks,
        "notice": "Phase 7-1은 저장 구조와 스키마만 검증합니다. 실제 공식 데이터 수집은 Phase 7-2에서 연결합니다."
    }
    write_json(ADMIN_OUT, payload)
    write_json(ANALYSIS_OUT, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())

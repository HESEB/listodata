#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build data freshness report for HESEB Livestock Terminal.

Phase 6-7 detects stale JSON, stale source contribution, and stale species
signals so the dashboard does not look normal when underlying data is old.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ADMIN = DATA / "admin"
ANALYSIS = DATA / "analysis"

WATCH_FILES = [
    (DATA / "market_dashboard.json", "Dashboard", 3),
    (DATA / "events" / "events_news.json", "뉴스 이벤트", 3),
    (DATA / "events" / "events_official.json", "공식자료 이벤트", 12),
    (DATA / "clean" / "events_clean.json", "Clean Layer", 3),
    (DATA / "clean" / "events_rejected.json", "Rejected Layer", 12),
    (ANALYSIS / "evidence_scores.json", "Evidence Score", 3),
    (ANALYSIS / "evidence_chains.json", "Evidence Chain", 6),
    (ANALYSIS / "history_prediction.json", "History Prediction", 12),
    (ADMIN / "quality_report.json", "Quality Report", 3),
    (ADMIN / "source_health.json", "Source Health", 6),
    (ADMIN / "quality_alerts.json", "Quality Alerts", 3),
    (DATA / "system" / "version.json", "Version", 3),
]

SPECIES = {
    "BEEF": "한우",
    "PORK": "돈육",
    "POULTRY": "계육",
    "DUCK": "오리",
    "EGG": "계란",
    "OTHER": "기타",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def age_hours(dt: datetime | None) -> float | None:
    if not dt:
        return None
    return round((now() - dt).total_seconds() / 3600, 2)


def rel(path: Path) -> str:
    try:
        return "app/data/" + str(path.relative_to(DATA)).replace("\\", "/")
    except Exception:
        return str(path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except Exception:
        return None


def item_count(data) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ["items", "species", "groups", "alerts", "sources"]:
            if isinstance(data.get(key), list):
                return len(data[key])
    return 0


def extract_updated_at(data, path: Path) -> datetime | None:
    if isinstance(data, dict):
        for key in ["updated_at", "generated_at", "build_time", "last_updated"]:
            dt = parse_dt(data.get(key))
            if dt:
                return dt
    return mtime(path)


def grade_by_age(hours: float | None, warn: int, critical: int) -> tuple[str, str]:
    if hours is None:
        return "risk", "갱신시간 없음"
    if hours >= critical:
        return "risk", "오래됨"
    if hours >= warn:
        return "watch", "주의"
    return "fresh", "신선"


def check_files() -> list[dict]:
    out = []
    for path, label, warn_hours in WATCH_FILES:
        critical_hours = warn_hours * 2
        exists = path.exists()
        data = read_json(path, {}) if exists else {}
        dt = extract_updated_at(data, path) if exists else None
        age = age_hours(dt)
        grade, grade_label = grade_by_age(age, warn_hours, critical_hours)
        issues = []
        if not exists:
            grade, grade_label = "risk", "파일 없음"
            issues.append("파일 없음")
        elif item_count(data) == 0 and path.name not in {"version.json"}:
            issues.append("데이터 건수 0건")
            if grade == "fresh":
                grade, grade_label = "watch", "데이터 없음"
        if age is None:
            issues.append("updated_at 또는 파일 갱신시간 확인 불가")
        out.append({
            "path": rel(path),
            "label": label,
            "exists": exists,
            "updated_at": dt.replace(microsecond=0).isoformat().replace("+00:00", "Z") if dt else None,
            "age_hours": age,
            "warn_hours": warn_hours,
            "critical_hours": critical_hours,
            "count": item_count(data),
            "freshness_grade": grade,
            "freshness_label": grade_label,
            "issues": issues,
        })
    return out


def items_from(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["items", "events", "data"]:
            if isinstance(data.get(key), list):
                return data[key]
    return []


def item_dt(item: dict) -> datetime | None:
    for key in ["published_at", "date", "event_date", "updated_at", "collected_at", "created_at"]:
        dt = parse_dt(item.get(key))
        if dt:
            return dt
    return None


def species_freshness() -> list[dict]:
    clean = items_from(read_json(DATA / "clean" / "events_clean.json", []))
    latest: dict[str, datetime] = {}
    counts: dict[str, int] = {k: 0 for k in SPECIES}
    for item in clean:
        species = item.get("species") or []
        if isinstance(species, str):
            species = [species]
        dt = item_dt(item)
        for sp in species:
            if sp not in SPECIES:
                continue
            counts[sp] = counts.get(sp, 0) + 1
            if dt and (sp not in latest or dt > latest[sp]):
                latest[sp] = dt
    out = []
    for sp, name in SPECIES.items():
        age = age_hours(latest.get(sp))
        warn = 24 if sp != "OTHER" else 48
        critical = warn * 2
        grade, label = grade_by_age(age, warn, critical)
        if counts.get(sp, 0) == 0:
            grade, label = "watch", "최근자료 없음"
        out.append({
            "species": sp,
            "name": name,
            "clean_count": counts.get(sp, 0),
            "latest_item_at": latest.get(sp).replace(microsecond=0).isoformat().replace("+00:00", "Z") if latest.get(sp) else None,
            "age_hours": age,
            "warn_hours": warn,
            "critical_hours": critical,
            "freshness_grade": grade,
            "freshness_label": label,
        })
    return out


def source_freshness() -> list[dict]:
    health = read_json(ADMIN / "source_health.json", {})
    rows = health.get("sources", []) if isinstance(health, dict) else []
    out = []
    for row in rows:
        activity = int(row.get("clean_count") or 0) + int(row.get("official_count") or 0) + int(row.get("news_count") or 0)
        grade = "fresh" if activity > 0 else "watch"
        label = "기여 있음" if activity > 0 else "최근 기여 없음"
        if row.get("health_grade") == "risk":
            grade, label = "risk", "소스 위험"
        out.append({
            "source": row.get("source"),
            "registered": row.get("registered"),
            "activity_count": activity,
            "health_grade": row.get("health_grade"),
            "freshness_grade": grade,
            "freshness_label": label,
            "recommended_action": row.get("recommended_action"),
        })
    return out


def build_alerts(files: list[dict], species: list[dict], sources: list[dict]) -> list[dict]:
    alerts = []
    for f in files:
        if f["freshness_grade"] in {"risk", "watch"}:
            alerts.append({
                "severity": "critical" if f["freshness_grade"] == "risk" else "warning",
                "category": "file",
                "title": f"{f['label']} 최신성 {f['freshness_label']}",
                "message": f"{f['path']} age={f['age_hours']}h / 기준 {f['warn_hours']}h",
                "recommended_action": "자동 업데이트 실행 결과와 JSON 생성 스크립트 확인",
            })
    for sp in species:
        if sp["freshness_grade"] in {"risk", "watch"}:
            alerts.append({
                "severity": "critical" if sp["freshness_grade"] == "risk" else "warning",
                "category": "species",
                "title": f"{sp['name']} 최신 자료 부족",
                "message": f"최근 Clean 자료 {sp['clean_count']}건 / 최신 age={sp['age_hours']}h",
                "recommended_action": "해당 축종 검색 쿼리·필터 사전·Source Center 연결 확인",
            })
    risk_sources = [s for s in sources if s.get("freshness_grade") == "risk"]
    if risk_sources:
        alerts.append({
            "severity": "warning",
            "category": "source",
            "title": "위험 소스 존재",
            "message": f"소스 위험 {len(risk_sources)}건",
            "recommended_action": "Source Health 페이지에서 소스별 기여도와 실패 원인 확인",
        })
    return alerts


def main() -> int:
    files = check_files()
    species = species_freshness()
    sources = source_freshness()
    alerts = build_alerts(files, species, sources)
    total = len(files) + len(species) + len(sources)
    fresh = sum(1 for x in files + species + sources if x.get("freshness_grade") == "fresh")
    watch = sum(1 for x in files + species + sources if x.get("freshness_grade") == "watch")
    risk = sum(1 for x in files + species + sources if x.get("freshness_grade") == "risk")
    score = round(fresh / max(total, 1) * 100)
    if risk:
        score = max(0, score - risk * 5)
    grade = "fresh" if score >= 90 and risk == 0 else ("watch" if score >= 70 else "risk")
    payload = {
        "updated_at": now_iso(),
        "policy": "phase6_freshness_report_v1",
        "notice": "파일·축종·소스별 최신성 기준을 점검해 오래된 데이터가 정상처럼 보이지 않도록 경고합니다.",
        "summary": {
            "total_checks": total,
            "fresh_count": fresh,
            "watch_count": watch,
            "risk_count": risk,
            "freshness_score": score,
            "freshness_grade": grade,
            "freshness_label": {"fresh": "신선", "watch": "주의", "risk": "위험"}.get(grade, grade),
            "alert_count": len(alerts),
        },
        "files": files,
        "species": species,
        "sources": sources,
        "alerts": alerts,
    }
    write_json(ADMIN / "freshness_report.json", payload)
    write_json(ANALYSIS / "freshness_report.json", payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

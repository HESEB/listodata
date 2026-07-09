#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build data freshness alerts for HESEB Livestock Terminal.

Phase 6-7 checks age of core JSON outputs and published/source timestamps inside
collected events. It creates a static freshness report for GitHub Pages.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ADMIN = DATA / "admin"
ANALYSIS = DATA / "analysis"

CORE_FILES = [
    (DATA / "market_dashboard.json", "Dashboard", 4),
    (DATA / "events" / "events_news.json", "뉴스 이벤트", 4),
    (DATA / "events" / "events_official.json", "공식자료 이벤트", 12),
    (DATA / "clean" / "events_clean.json", "Clean Layer", 4),
    (ANALYSIS / "evidence_scores.json", "Evidence Score", 4),
    (ANALYSIS / "evidence_chains.json", "Evidence Chain", 6),
    (ANALYSIS / "history_prediction.json", "History Prediction", 24),
    (ANALYSIS / "source_health.json", "Source Health", 24),
    (ADMIN / "quality_alerts.json", "Quality Alerts", 6),
]

SPECIES = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG", "OTHER"]
SPECIES_LABEL = {"BEEF":"한우","PORK":"돈육","POULTRY":"계육","DUCK":"오리","EGG":"계란","OTHER":"기타"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    for fmt in [None, "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"]:
        try:
            if fmt:
                return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
            d = datetime.fromisoformat(s)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def hours_old(dt: datetime | None) -> float | None:
    if not dt:
        return None
    return round((now() - dt).total_seconds() / 3600, 2)


def items_from(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ["items", "events", "data"]:
            if isinstance(data.get(k), list):
                return data[k]
    return []


def best_item_date(item: dict) -> datetime | None:
    for key in ["published_at", "published", "date", "created_at", "updated_at", "collected_at", "source_published_at"]:
        d = parse_dt(item.get(key))
        if d:
            return d
    return None


def file_check(path: Path, label: str, threshold_hours: int) -> dict:
    exists = path.exists()
    mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) if exists else None
    age = hours_old(mtime)
    status = "ok"
    issues = []
    if not exists:
        status = "critical"
        issues.append("파일 없음")
    elif age is not None and age > threshold_hours * 2:
        status = "critical"
        issues.append(f"갱신 {age}시간 경과")
    elif age is not None and age > threshold_hours:
        status = "warning"
        issues.append(f"권장 갱신주기 {threshold_hours}시간 초과")
    return {"path": "app/data/" + str(path.relative_to(DATA)).replace("\\", "/") if path.exists() or DATA in path.parents else str(path), "label": label, "threshold_hours": threshold_hours, "exists": exists, "updated_at": mtime.isoformat().replace("+00:00", "Z") if mtime else None, "age_hours": age, "status": status, "issues": issues}


def species_freshness(clean_items: list[dict]) -> list[dict]:
    out = []
    for sp in SPECIES:
        rows = [x for x in clean_items if sp in (x.get("species") or [])]
        dates = [best_item_date(x) for x in rows]
        dates = [d for d in dates if d]
        latest = max(dates) if dates else None
        age = hours_old(latest)
        threshold = 48 if sp != "OTHER" else 72
        status = "ok"
        issues = []
        if not rows:
            status = "warning"
            issues.append("최근 Clean 자료 없음")
        elif not latest:
            status = "warning"
            issues.append("자료 날짜 확인 불가")
        elif age is not None and age > threshold * 2:
            status = "critical"
            issues.append(f"최신 자료 {age}시간 경과")
        elif age is not None and age > threshold:
            status = "warning"
            issues.append(f"최신 자료 권장 기준 {threshold}시간 초과")
        out.append({"species": sp, "label": SPECIES_LABEL.get(sp, sp), "item_count": len(rows), "latest_at": latest.isoformat().replace("+00:00", "Z") if latest else None, "age_hours": age, "threshold_hours": threshold, "status": status, "issues": issues})
    return out


def source_freshness(source_health: dict) -> list[dict]:
    out = []
    for s in source_health.get("sources", []) if isinstance(source_health, dict) else []:
        clean = int(s.get("clean_count") or 0)
        official = int(s.get("official_count") or 0)
        registered = bool(s.get("registered"))
        status = "ok"
        issues = []
        if registered and clean + official == 0:
            status = "warning"
            issues.append("등록 소스이나 최근 기여 없음")
        if s.get("health_grade") == "risk":
            status = "critical"
            issues.append("소스 헬스 위험")
        out.append({"source": s.get("source"), "registered": registered, "clean_count": clean, "official_count": official, "health_grade": s.get("health_grade"), "status": status, "issues": issues})
    return out


def alerts(files, species, sources) -> list[dict]:
    out = []
    for row in files:
        if row["status"] != "ok":
            out.append({"severity": row["status"], "category": "file", "title": f"{row['label']} 최신성 경고", "message": "; ".join(row["issues"]), "target": row["path"], "recommended_action": "자동 업데이트 실행 상태와 파일 생성 스크립트 확인"})
    for row in species:
        if row["status"] != "ok":
            out.append({"severity": row["status"], "category": "species", "title": f"{row['label']} 최신자료 부족", "message": "; ".join(row["issues"]), "target": row["species"], "recommended_action": "해당 축종 검색 쿼리와 공식자료 링크 확인"})
    for row in sources:
        if row["status"] != "ok":
            out.append({"severity": row["status"], "category": "source", "title": f"{row['source']} 소스 최신성 경고", "message": "; ".join(row["issues"]), "target": row["source"], "recommended_action": "Source Health 및 Source Center 등록 링크 확인"})
    return out


def main() -> int:
    clean = items_from(read_json(DATA / "clean" / "events_clean.json", {}))
    source_health = read_json(ADMIN / "source_health.json", {})
    file_rows = [file_check(*x) for x in CORE_FILES]
    sp_rows = species_freshness(clean)
    src_rows = source_freshness(source_health)
    alert_rows = alerts(file_rows, sp_rows, src_rows)
    critical = sum(1 for x in alert_rows if x["severity"] == "critical")
    warning = sum(1 for x in alert_rows if x["severity"] == "warning")
    grade = "critical" if critical else ("warning" if warning else "fresh")
    payload = {
        "updated_at": now_iso(),
        "policy": "phase6_freshness_alerts_v1",
        "summary": {"grade": grade, "label": {"fresh":"최신","warning":"주의","critical":"위험"}[grade], "critical_count": critical, "warning_count": warning, "alert_count": len(alert_rows), "file_count": len(file_rows), "species_count": len(sp_rows), "source_count": len(src_rows)},
        "files": file_rows,
        "species": sp_rows,
        "sources": src_rows,
        "alerts": alert_rows,
        "notice": "파일 갱신시간, 축종별 최신 자료, 등록 소스 기여 여부를 기준으로 최신성 경고를 생성합니다."
    }
    write_json(ADMIN / "freshness_alerts.json", payload)
    write_json(ANALYSIS / "freshness_alerts.json", payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

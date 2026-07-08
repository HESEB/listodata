#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""History & Prediction Engine draft for HESEB Livestock Terminal.

Phase 2-5:
- Append daily/hourly Evidence Score snapshots.
- Keep a compact signal history per species.
- Calculate 7/14/30 point trend summaries.
- Generate a prediction draft based on signal trend, confidence, and conflict state.

This is not a price forecast. It is a directional reference based on collected
public evidence signals.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
ANALYSIS = DATA / "analysis"
ADMIN = DATA / "admin"
HISTORY = DATA / "history"

SPECIES_ORDER = ["BEEF", "PORK", "POULTRY", "DUCK", "EGG", "OTHER"]
SPECIES_LABEL = {"BEEF":"한우","PORK":"돈육","POULTRY":"계육","DUCK":"오리","EGG":"계란","OTHER":"기타"}
MAX_HISTORY_ROWS = 900


def now_dt() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_dt().isoformat().replace("+00:00", "Z")


def today_key() -> str:
    return now_dt().strftime("%Y-%m-%d")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot_from_score(score: dict) -> dict:
    conflict = score.get("conflict") or {}
    hold = score.get("hold_decision") or {}
    return {
        "date": today_key(),
        "timestamp": now_iso(),
        "species": score.get("id"),
        "name": score.get("name") or SPECIES_LABEL.get(score.get("id"), score.get("id")),
        "signal_score": score.get("signal_score", 0),
        "direction": score.get("direction", "hold"),
        "status": score.get("status", "판단 유보"),
        "confidence_score": score.get("confidence_score", 0),
        "coverage_rate": score.get("coverage_rate", 0),
        "quality_score": score.get("quality_score", 0),
        "evidence_count": score.get("evidence_count", 0),
        "official_count": score.get("official_count", 0),
        "score_breakdown": score.get("score_breakdown", {}),
        "conflict_severity": conflict.get("severity", "none"),
        "has_conflict": bool(conflict.get("has_conflict")),
        "hold_reasons": hold.get("reasons", []),
        "reason": score.get("reason", ""),
    }


def merge_history(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    # Keep latest row per species/date. This avoids runaway growth when workflow runs hourly.
    by_key = {}
    for row in existing:
        key = (row.get("species"), row.get("date"))
        if key[0] and key[1]:
            by_key[key] = row
    for row in new_rows:
        by_key[(row.get("species"), row.get("date"))] = row
    rows = sorted(by_key.values(), key=lambda x: (x.get("date", ""), x.get("species", "")))
    return rows[-MAX_HISTORY_ROWS:]


def rows_for_species(history: list[dict], species: str) -> list[dict]:
    return sorted([x for x in history if x.get("species") == species], key=lambda x: x.get("date", ""))


def trend_window(rows: list[dict], window: int) -> dict:
    subset = rows[-window:]
    if not subset:
        return {"window_days": window, "status": "insufficient", "direction": "hold", "change": 0, "average_signal": 0, "confidence": 0, "memo": "누적 이력 없음"}
    first = subset[0]
    last = subset[-1]
    change = round((last.get("signal_score", 0) or 0) - (first.get("signal_score", 0) or 0), 1)
    avg = round(sum(x.get("signal_score", 0) or 0 for x in subset) / len(subset), 1)
    conf = round(sum(x.get("confidence_score", 0) or 0 for x in subset) / len(subset), 1)
    if len(subset) < max(2, min(window, 4)):
        direction = "hold"
        status = "insufficient"
        memo = f"{len(subset)}일치 이력만 존재하여 참고 수준"
    elif change >= 8 and avg >= 55:
        direction = "up"
        status = "rising"
        memo = f"{window}일 구간 신호 {change:+.1f}점 상승"
    elif change <= -8 and avg <= 55:
        direction = "down"
        status = "falling"
        memo = f"{window}일 구간 신호 {change:+.1f}점 하락"
    elif abs(change) < 8:
        direction = "neutral"
        status = "sideways"
        memo = f"{window}일 구간 신호 변화 제한적"
    else:
        direction = "mixed"
        status = "mixed"
        memo = f"{window}일 구간 신호 혼조"
    return {
        "window_days": window,
        "status": status,
        "direction": direction,
        "change": change,
        "average_signal": avg,
        "confidence": conf,
        "start_score": first.get("signal_score", 0),
        "end_score": last.get("signal_score", 0),
        "sample_days": len(subset),
        "memo": memo,
    }


def prediction_label(windows: dict, latest: dict | None) -> tuple[str, str, int]:
    if not latest:
        return "판단 유보", "이력 데이터 없음", 0
    w7 = windows.get("7d", {})
    w14 = windows.get("14d", {})
    w30 = windows.get("30d", {})
    latest_conf = latest.get("confidence_score", 0) or 0
    conflict = latest.get("conflict_severity") in {"high", "medium"}
    if latest.get("direction") == "hold" or latest_conf < 40:
        return "판단 유보", "현재 신뢰도 또는 근거 부족", latest_conf
    score = 0
    for w, weight in [(w7, 0.50), (w14, 0.30), (w30, 0.20)]:
        direction = w.get("direction")
        if direction == "up":
            score += 1.0 * weight
        elif direction == "down":
            score -= 1.0 * weight
        elif direction == "mixed":
            score += 0.15 * weight
    if latest.get("direction") == "up":
        score += 0.35
    elif latest.get("direction") == "down":
        score -= 0.35
    if conflict:
        score *= 0.55
    confidence = round(min(100, latest_conf * (0.75 if conflict else 1.0)))
    if score >= 0.55:
        return "상방 가능성", "최근 신호와 현재 방향성이 상방으로 정렬", confidence
    if score <= -0.55:
        return "하방 가능성", "최근 신호와 현재 방향성이 하방으로 정렬", confidence
    return "보합/혼조", "신호 변화가 제한적이거나 방향성이 혼재", confidence


def market_memory_events(history: list[dict]) -> list[dict]:
    events = []
    by_species = defaultdict(list)
    for row in history:
        by_species[row.get("species")].append(row)
    for sp, rows in by_species.items():
        rows = sorted(rows, key=lambda x: x.get("date", ""))
        for prev, cur in zip(rows, rows[1:]):
            delta = (cur.get("signal_score", 0) or 0) - (prev.get("signal_score", 0) or 0)
            if abs(delta) >= 12:
                events.append({
                    "date": cur.get("date"),
                    "species": sp,
                    "name": SPECIES_LABEL.get(sp, sp),
                    "event_type": "signal_jump" if delta > 0 else "signal_drop",
                    "change": round(delta, 1),
                    "from_score": prev.get("signal_score", 0),
                    "to_score": cur.get("signal_score", 0),
                    "memo": f"{SPECIES_LABEL.get(sp, sp)} 신호 {delta:+.1f}점 변동",
                })
    return events[-80:]


def build_predictions(history: list[dict]) -> dict:
    result = []
    for sp in SPECIES_ORDER:
        rows = rows_for_species(history, sp)
        latest = rows[-1] if rows else None
        windows = {"7d": trend_window(rows, 7), "14d": trend_window(rows, 14), "30d": trend_window(rows, 30)}
        label, memo, conf = prediction_label(windows, latest)
        result.append({
            "id": sp,
            "name": SPECIES_LABEL.get(sp, sp),
            "latest": latest,
            "windows": windows,
            "prediction": {
                "label": label,
                "memo": memo,
                "confidence": conf,
                "horizon": "7/14/30일 참고 방향성",
                "disclaimer": "가격 예측이 아니라 수집 근거 신호의 방향성 참고값입니다.",
            },
        })
    return {"updated_at": now_iso(), "policy": "phase2_history_prediction_v1", "items": result}


def main() -> int:
    scores = read_json(ANALYSIS / "evidence_scores.json", {"species": []})
    history_payload = read_json(HISTORY / "signal_history.json", {"items": []})
    current_rows = [snapshot_from_score(x) for x in scores.get("species", [])]
    history_rows = merge_history(history_payload.get("items", []), current_rows)
    events = market_memory_events(history_rows)
    predictions = build_predictions(history_rows)

    history_out = {
        "updated_at": now_iso(),
        "policy": "phase2_signal_history_v1",
        "notice": "Evidence Score 일자별 누적 이력입니다. 자동 업데이트가 여러 번 실행되어도 같은 날짜/축종은 최신값으로 갱신됩니다.",
        "items": history_rows,
    }
    memory_out = {
        "updated_at": now_iso(),
        "policy": "phase2_market_memory_draft_v1",
        "notice": "신호 급변 이벤트를 자동 기록하는 시장 메모리 초안입니다.",
        "items": events,
    }
    write_json(HISTORY / "signal_history.json", history_out)
    write_json(ANALYSIS / "history_prediction.json", predictions)
    write_json(ADMIN / "history_prediction.json", predictions)
    write_json(ANALYSIS / "market_memory.json", memory_out)
    write_json(ADMIN / "market_memory.json", memory_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

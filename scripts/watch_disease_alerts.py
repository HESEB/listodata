#!/usr/bin/env python3
"""Hourly livestock disease alert watcher.

This script is designed for GitHub Actions. It fetches configured public pages,
searches disease keywords, and writes app/data/disease_alerts.json.

It is conservative:
- It does not invent outbreaks.
- If a page cannot be fetched or parsed, it records source status.
- Keyword hits are alerts, not confirmed outbreaks, unless official wording is detected.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from html import unescape
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "app" / "data" / "disease_watch.json"
OUTPUT = ROOT / "app" / "data" / "disease_alerts.json"
KST = timezone(timedelta(hours=9))

OFFICIAL_CONFIRM_PATTERNS = [
    "발생", "확인", "양성", "확진", "방역대", "이동제한", "살처분", "정밀검사", "중앙사고수습본부"
]


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def strip_html(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_url(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 HESEB-Livestock-Terminal disease watcher",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            raw = res.read()
            content_type = res.headers.get("content-type", "")
            for enc in ["utf-8", "euc-kr", "cp949"]:
                try:
                    html = raw.decode(enc)
                    return {
                        "ok": True,
                        "status": getattr(res, "status", 200),
                        "encoding": enc,
                        "content_type": content_type,
                        "text": strip_html(html),
                    }
                except UnicodeDecodeError:
                    continue
            return {"ok": False, "error": "decode_failed", "text": ""}
    except Exception as e:
        return {"ok": False, "error": str(e), "text": ""}


def snippet(text: str, keyword: str, size: int = 120) -> str:
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return text[:size]
    start = max(0, idx - size // 2)
    end = min(len(text), idx + len(keyword) + size // 2)
    return text[start:end].strip()


def is_official_confirmed(text: str) -> bool:
    return any(p in text for p in OFFICIAL_CONFIRM_PATTERNS)


def severity_rank(sev: str) -> int:
    return {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(sev, 0)


def build_alerts(config: Dict[str, Any]) -> Dict[str, Any]:
    sources = config.get("sources", [])
    keywords = config.get("keywords", [])
    source_status: List[Dict[str, Any]] = []
    alerts: List[Dict[str, Any]] = []

    for source in sources:
        fetched = fetch_url(source["url"])
        text = fetched.get("text", "")
        source_status.append({
            "source_id": source.get("source_id"),
            "name": source.get("name"),
            "url": source.get("url"),
            "ok": bool(fetched.get("ok")),
            "status": fetched.get("status"),
            "encoding": fetched.get("encoding"),
            "error": fetched.get("error"),
            "checked_at": now_kst(),
        })
        if not fetched.get("ok") or not text:
            continue

        for kw in keywords:
            matched_terms = [term for term in kw.get("names", []) if term.lower() in text.lower()]
            if not matched_terms:
                continue
            local_snip = snippet(text, matched_terms[0])
            confirmed = is_official_confirmed(local_snip)
            base_sev = kw.get("severity", "MEDIUM")
            alert_sev = base_sev if confirmed else ("HIGH" if base_sev == "CRITICAL" else base_sev)
            alerts.append({
                "alert_id": f"{kw.get('id')}_{source.get('source_id')}",
                "disease_id": kw.get("id"),
                "disease_terms": matched_terms,
                "severity": alert_sev,
                "confirmed_by_wording": confirmed,
                "species": kw.get("species", []),
                "source_id": source.get("source_id"),
                "source_name": source.get("name"),
                "url": source.get("url"),
                "title": f"{matched_terms[0]} 관련 공식/자료 페이지 키워드 감지",
                "summary": local_snip,
                "checked_at": now_kst(),
                "data_status": "KEYWORD_DETECTED",
                "data_status_label": "키워드 감지"
            })

    # Deduplicate by disease/source and sort by severity
    dedup: Dict[str, Dict[str, Any]] = {}
    for alert in alerts:
        key = alert["alert_id"]
        if key not in dedup or severity_rank(alert["severity"]) > severity_rank(dedup[key]["severity"]):
            dedup[key] = alert
    final_alerts = sorted(dedup.values(), key=lambda x: (severity_rank(x.get("severity", "")), x.get("checked_at", "")), reverse=True)

    return {
        "updated_at": now_kst(),
        "generated_by": "scripts/watch_disease_alerts.py",
        "notice": "공식 페이지 및 지정 키워드 기반 조기경보입니다. 키워드 감지는 확진 의미가 아니며, 최종 판단은 원문 확인이 필요합니다.",
        "manual_refresh": config.get("manual_refresh"),
        "watch_interval": config.get("watch_interval", "hourly"),
        "alert_count": len(final_alerts),
        "alerts": final_alerts[:20],
        "source_status": source_status,
    }


def main() -> int:
    if not CONFIG.exists():
        print(f"missing config: {CONFIG}", file=sys.stderr)
        return 1
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    result = build_alerts(config)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {result['alert_count']} alerts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

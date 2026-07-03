#!/usr/bin/env python3
"""대한양계협회 닭 지육가 HTML adapter.

The adapter is intentionally conservative:
- stdlib only, no external dependencies
- fetches a single configured URL
- extracts numeric-looking values from HTML tables
- writes a raw snapshot for audit/debug
- never mutates production metrics directly

The exact table layout of the site may change. If extraction confidence is low,
callers should keep the previous/manual snapshot and mark the source status as
`adapter_failed` rather than overwriting market data.
"""
from __future__ import annotations

import html
import json
import re
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

KST = timezone(timedelta(hours=9))
DEFAULT_TIMEOUT = 20


@dataclass
class ChickenPriceSnapshot:
    source_id: str
    fetched_at: str
    url: str
    status: str
    latest_label: Optional[str]
    latest_value: Optional[float]
    numeric_values: List[float]
    message: str


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def strip_tags(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_html(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "HESEB-Livestock-Terminal/1.0 (+https://heseb.github.io/listodata)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
    # Korean public sites are often UTF-8 or EUC-KR. Try both safely.
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_numeric_values(text: str) -> List[float]:
    # Remove dates like 2026.07.03 from numeric scoring noise as much as possible.
    cleaned = re.sub(r"20\d{2}[.\-/년]\s*\d{1,2}([.\-/월]\s*\d{1,2}일?)?", " ", text)
    nums: List[float] = []
    for m in re.finditer(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{3,5})(?:\.\d+)?(?!\d)", cleaned):
        token = m.group(0).replace(",", "")
        try:
            value = float(token)
        except ValueError:
            continue
        # Chicken carcass price is usually in a practical 1,000~9,999 range.
        if 1000 <= value <= 9999:
            nums.append(value)
    return nums


def infer_latest_label(text: str) -> Optional[str]:
    m = re.search(r"(20\d{2}[.\-/년]\s*\d{1,2}([.\-/월]\s*\d{1,2}일?)?)", text)
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(1))


def collect(source: Dict[str, Any]) -> ChickenPriceSnapshot:
    url = source["url"]
    try:
        page = fetch_html(url)
        text = strip_tags(page)
        nums = extract_numeric_values(text)
        latest = nums[-1] if nums else None
        status = "adapter_success" if latest is not None else "adapter_no_value"
        message = "닭 지육가 후보 숫자를 추출했습니다." if latest is not None else "HTML에서 가격 후보 숫자를 찾지 못했습니다."
        return ChickenPriceSnapshot(
            source_id=source.get("id", "CHICKEN_PRICE_9_10"),
            fetched_at=now_kst(),
            url=url,
            status=status,
            latest_label=infer_latest_label(text),
            latest_value=latest,
            numeric_values=nums[-30:],
            message=message,
        )
    except Exception as exc:  # noqa: BLE001 - status reporting must not break pipeline
        return ChickenPriceSnapshot(
            source_id=source.get("id", "CHICKEN_PRICE_9_10"),
            fetched_at=now_kst(),
            url=url,
            status="adapter_failed",
            latest_label=None,
            latest_value=None,
            numeric_values=[],
            message=f"수집 실패: {type(exc).__name__}: {exc}",
        )


def write_snapshot(path: Path, snapshot: ChickenPriceSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

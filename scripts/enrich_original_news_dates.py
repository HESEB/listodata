#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enrich collected news with publication-date metadata from original HTML.

Best-effort only: article failures never fail the workflow. Dates are stored as
candidates and never overwrite published_at automatically.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY_PATH = DATA / "design" / "original_news_date_enrichment_policy.json"
EVENT_PATHS = [DATA / "events" / "events_news.json", DATA / "events" / "events_official.json"]
ADMIN_OUT = DATA / "admin" / "original_news_date_enrichment.json"
ANALYSIS_OUT = DATA / "analysis" / "original_news_date_enrichment.json"
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


def parse_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            pass
    return None


def safe_url(url: str, blocked_hosts: set[str]) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        if host in blocked_hosts or host.endswith(".local"):
            return False
        for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80)):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except Exception:
        return False


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[tuple[str, str]] = []
        self.times: list[str] = []
        self.canonical: str | None = None
        self._json_ld = False
        self._json_chunks: list[str] = []
        self.json_ld_texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag.lower() == "meta":
            key = values.get("property") or values.get("name") or values.get("itemprop")
            content = values.get("content")
            if key and content:
                self.meta.append((key, content))
        elif tag.lower() == "time" and values.get("datetime"):
            self.times.append(values["datetime"])
        elif tag.lower() == "link" and "canonical" in values.get("rel", "").lower():
            self.canonical = values.get("href") or self.canonical
        elif tag.lower() == "script" and "ld+json" in values.get("type", "").lower():
            self._json_ld = True
            self._json_chunks = []

    def handle_data(self, data: str) -> None:
        if self._json_ld:
            self._json_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._json_ld:
            self.json_ld_texts.append("".join(self._json_chunks))
            self._json_ld = False
            self._json_chunks = []


def walk_json_dates(value: Any, fields: set[str], out: list[tuple[str, Any]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in fields:
                out.append((key, item))
            walk_json_dates(item, fields, out)
    elif isinstance(value, list):
        for item in value:
            walk_json_dates(item, fields, out)


def fetch_html(url: str, timeout: int, max_bytes: int) -> tuple[str, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        final_url = response.geturl()
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise RuntimeError("response_too_large")
    if "html" not in content_type:
        raise RuntimeError("non_html_response")
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type)
    if match:
        charset = match.group(1)
    return raw.decode(charset, errors="replace"), final_url, content_type


def extract(html: str, page_url: str, policy: dict) -> dict:
    parser = MetadataParser()
    parser.feed(html)
    candidates: list[dict] = []
    source_policy = {row["source"]: row for row in policy.get("date_sources", []) if isinstance(row, dict) and row.get("source")}

    json_fields = set(source_policy.get("json_ld", {}).get("fields", []))
    for text in parser.json_ld_texts:
        try:
            doc = json.loads(text.strip())
        except Exception:
            continue
        found: list[tuple[str, Any]] = []
        walk_json_dates(doc, json_fields, found)
        for field, value in found:
            parsed = parse_date(value)
            if parsed:
                candidates.append({"published_at": parsed, "source": "json_ld", "field": field, "confidence": source_policy.get("json_ld", {}).get("confidence", 100), "raw_value": str(value)[:160]})

    for key, value in parser.meta:
        low = key.lower()
        source = "open_graph" if low in {"article:published_time", "og:published_time"} else "meta"
        allowed = {x.lower() for x in source_policy.get(source, {}).get("fields", [])}
        if low not in allowed:
            continue
        parsed = parse_date(value)
        if parsed:
            candidates.append({"published_at": parsed, "source": source, "field": key, "confidence": source_policy.get(source, {}).get("confidence", 90), "raw_value": value[:160]})

    for value in parser.times:
        parsed = parse_date(value)
        if parsed:
            candidates.append({"published_at": parsed, "source": "time_tag", "field": "datetime", "confidence": source_policy.get("time_tag", {}).get("confidence", 85), "raw_value": value[:160]})

    dedup: dict[tuple[str, str], dict] = {}
    for row in candidates:
        key = (row["published_at"], row["source"])
        if key not in dedup or int(row.get("confidence", 0)) > int(dedup[key].get("confidence", 0)):
            dedup[key] = row
    ordered = sorted(dedup.values(), key=lambda x: (int(x.get("confidence", 0)), x.get("published_at", "")), reverse=True)
    canonical = urllib.parse.urljoin(page_url, parser.canonical) if parser.canonical else None
    return {"candidates": ordered[:20], "canonical_url": canonical}


def main() -> int:
    policy = read_json(POLICY_PATH, {})
    if not policy.get("enabled", True):
        return 0
    limit = int(policy.get("max_articles_per_run", 40))
    timeout = int(policy.get("request_timeout_seconds", 12))
    max_bytes = int(policy.get("max_response_bytes", 1200000))
    blocked = set((policy.get("safety") or {}).get("blocked_hosts", []))
    processed = enriched = failed = skipped = 0
    source_counts: dict[str, int] = {}
    failures: list[dict] = []

    for path in EVENT_PATHS:
        payload = read_json(path, {"items": []})
        changed = False
        items = payload.get("items", []) or []
        for item in items:
            if processed >= limit:
                break
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("source_url") or "").strip()
            if not url or not safe_url(url, blocked):
                skipped += 1
                continue
            processed += 1
            try:
                html, final_url, content_type = fetch_html(url, timeout, max_bytes)
                result = extract(html, final_url, policy)
                canonical = result.get("canonical_url")
                if policy.get("retry_canonical_once", True) and canonical and canonical != final_url and safe_url(canonical, blocked):
                    try:
                        html2, final2, content2 = fetch_html(canonical, timeout, max_bytes)
                        result2 = extract(html2, final2, policy)
                        if len(result2.get("candidates", [])) >= len(result.get("candidates", [])):
                            result, final_url, content_type = result2, final2, content2
                    except Exception:
                        pass
                candidates = result.get("candidates", [])
                item["original_date_metadata"] = {
                    "checked_at": now_iso(), "status": "found" if candidates else "not_found",
                    "requested_url": url, "final_url": final_url, "content_type": content_type,
                    "canonical_url": result.get("canonical_url"), "candidates": candidates,
                    "best_candidate": candidates[0] if candidates else None,
                    "auto_applied": False,
                }
                for row in candidates:
                    src = str(row.get("source") or "unknown")
                    source_counts[src] = source_counts.get(src, 0) + 1
                if candidates:
                    enriched += 1
                changed = True
            except Exception as exc:
                failed += 1
                item["original_date_metadata"] = {"checked_at": now_iso(), "status": "failed", "requested_url": url, "error": str(exc)[:240], "auto_applied": False}
                failures.append({"event_id": item.get("event_id"), "url": url, "error": str(exc)[:240]})
                changed = True
        if changed:
            payload["original_date_enrichment"] = {"updated_at": now_iso(), "policy": policy.get("policy"), "processed_count": processed}
            write_json(path, payload)
        if processed >= limit:
            break

    status = {
        "updated_at": now_iso(), "policy": policy.get("policy", "phase8_original_news_date_enrichment_v1"),
        "summary": {"processed_count": processed, "enriched_count": enriched, "failed_count": failed, "skipped_count": skipped, "source_counts": source_counts, "auto_applied_count": 0},
        "failures": failures[:100], "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, status)
    write_json(ANALYSIS_OUT, status)
    print(json.dumps(status["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

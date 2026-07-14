#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enrich news dates and report publisher-level collection health.

Best effort only. Public metadata differences may be handled by publisher rules,
but login, paywall, and bot-protection bypasses are never attempted.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
POLICY_PATH = DATA / "design" / "original_news_date_enrichment_policy.json"
EXCEPTIONS_PATH = DATA / "config" / "original_news_publisher_exceptions.json"
EVENT_PATHS = [DATA / "events" / "events_news.json", DATA / "events" / "events_official.json"]
ADMIN_OUT = DATA / "admin" / "original_news_date_enrichment.json"
ANALYSIS_OUT = DATA / "analysis" / "original_news_date_enrichment.json"
DEFAULT_USER_AGENT = "HESEB-Livestock-Terminal/2.1 (+https://heseb.github.io/listodata/)"
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


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


def hostname(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def publisher_key(item: dict, url: str) -> tuple[str, str]:
    domain = hostname(url)
    display = str(item.get("publisher") or item.get("source_title") or domain or "unknown").strip()
    return domain or display.lower(), display


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
        self.times: list[dict[str, str]] = []
        self.canonical: str | None = None
        self._json_ld = False
        self._json_chunks: list[str] = []
        self.json_ld_texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(k).lower(): str(v or "") for k, v in attrs}
        low_tag = tag.lower()
        if low_tag == "meta":
            key = values.get("property") or values.get("name") or values.get("itemprop")
            content = values.get("content")
            if key and content:
                self.meta.append((key, content))
        elif low_tag == "time":
            self.times.append(values)
        elif low_tag == "link" and "canonical" in values.get("rel", "").lower():
            self.canonical = values.get("href") or self.canonical
        elif low_tag == "script" and "ld+json" in values.get("type", "").lower():
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


def publisher_rule(url: str, config: dict) -> dict:
    defaults = dict(config.get("defaults") or {})
    host = hostname(url)
    matched = None
    for row in config.get("publishers", []) or []:
        if not isinstance(row, dict) or not row.get("enabled", True):
            continue
        domains = [str(x).lower().removeprefix("www.") for x in row.get("domains", []) or []]
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            matched = row
            defaults.update(row)
            break
    defaults["matched_exception_id"] = (matched or {}).get("id")
    return defaults


def fetch_html(url: str, timeout: int, max_bytes: int, user_agent: str) -> tuple[str, str, str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        final_url = response.geturl()
        status = int(getattr(response, "status", 200) or 200)
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise RuntimeError("response_too_large")
    if "html" not in content_type:
        raise RuntimeError("non_html_response")
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type)
    if match:
        charset = match.group(1)
    return raw.decode(charset, errors="replace"), final_url, content_type, status


def extract(html: str, page_url: str, policy: dict, rule: dict) -> dict:
    parser = MetadataParser()
    parser.feed(html)
    candidates: list[dict] = []
    source_policy = {row["source"]: row for row in policy.get("date_sources", []) if isinstance(row, dict) and row.get("source")}

    json_fields = set(source_policy.get("json_ld", {}).get("fields", [])) | set(rule.get("extra_json_ld_fields", []) or [])
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

    extra_meta = {str(x).lower() for x in rule.get("extra_meta_fields", []) or []}
    for key, value in parser.meta:
        low = key.lower()
        source = "open_graph" if low in {"article:published_time", "og:published_time"} else "meta"
        allowed = {x.lower() for x in source_policy.get(source, {}).get("fields", [])} | extra_meta
        if low not in allowed:
            continue
        parsed = parse_date(value)
        if parsed:
            candidates.append({"published_at": parsed, "source": source, "field": key, "confidence": source_policy.get(source, {}).get("confidence", 90), "raw_value": value[:160]})

    time_attrs = {"datetime"} | {str(x).lower() for x in rule.get("extra_time_attributes", []) or []}
    for values in parser.times:
        for attr in time_attrs:
            value = values.get(attr)
            parsed = parse_date(value)
            if parsed:
                candidates.append({"published_at": parsed, "source": "time_tag", "field": attr, "confidence": source_policy.get("time_tag", {}).get("confidence", 85), "raw_value": str(value)[:160]})

    dedup: dict[tuple[str, str], dict] = {}
    for row in candidates:
        key = (row["published_at"], row["source"])
        if key not in dedup or int(row.get("confidence", 0)) > int(dedup[key].get("confidence", 0)):
            dedup[key] = row
    ordered = sorted(dedup.values(), key=lambda x: (int(x.get("confidence", 0)), x.get("published_at", "")), reverse=True)
    canonical = urllib.parse.urljoin(page_url, parser.canonical) if parser.canonical else None
    return {"candidates": ordered[:20], "canonical_url": canonical}


def classify_failure(exc: Exception) -> tuple[str, int | None]:
    if isinstance(exc, urllib.error.HTTPError):
        code = int(exc.code)
        if code in {401, 403, 406, 429}:
            return "http_blocked", code
        if code >= 500:
            return "http_server_error", code
        return "http_error", code
    text = str(exc).lower()
    if "response_too_large" in text:
        return "too_large", None
    if "non_html_response" in text:
        return "non_html", None
    if any(word in text for word in ["timeout", "timed out", "urlopen error", "name or service not known"]):
        return "network", None
    return "other_error", None


def health_status(attempts: int, access_rate: float, found_rate: float, policy: dict) -> str:
    cfg = policy.get("publisher_health") or {}
    if attempts < int(cfg.get("minimum_attempts_for_rating", 3)):
        return "insufficient_data"
    if access_rate >= float(cfg.get("healthy_access_rate", 80)) and found_rate >= float(cfg.get("healthy_date_found_rate", 60)):
        return "healthy"
    if access_rate >= float(cfg.get("warning_access_rate", 50)) and found_rate >= float(cfg.get("warning_date_found_rate", 25)):
        return "warning"
    return "critical"


def main() -> int:
    policy = read_json(POLICY_PATH, {})
    exceptions = read_json(EXCEPTIONS_PATH, {"defaults": {}, "publishers": []})
    if not policy.get("enabled", True):
        return 0
    limit = int(policy.get("max_articles_per_run", 40))
    default_timeout = int(policy.get("request_timeout_seconds", 12))
    max_bytes = int(policy.get("max_response_bytes", 1200000))
    blocked = set((policy.get("safety") or {}).get("blocked_hosts", []))
    processed = enriched = failed = skipped = accessed = 0
    source_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    failures: list[dict] = []
    publisher_stats: dict[str, dict] = {}

    def stat_for(key: str, display: str, domain: str) -> dict:
        return publisher_stats.setdefault(key, {"publisher_key": key, "publisher": display, "domain": domain, "attempted_count": 0, "access_success_count": 0, "date_found_count": 0, "metadata_not_found_count": 0, "failed_count": 0, "failure_categories": {}, "exception_ids": []})

    for path in EVENT_PATHS:
        payload = read_json(path, {"items": []})
        changed = False
        for item in payload.get("items", []) or []:
            if processed >= limit:
                break
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("source_url") or "").strip()
            if not url or not safe_url(url, blocked):
                skipped += 1
                continue
            processed += 1
            key, display = publisher_key(item, url)
            domain = hostname(url)
            stat = stat_for(key, display, domain)
            stat["attempted_count"] += 1
            rule = publisher_rule(url, exceptions)
            exception_id = rule.get("matched_exception_id")
            if exception_id and exception_id not in stat["exception_ids"]:
                stat["exception_ids"].append(exception_id)
            timeout = int(rule.get("timeout_seconds") or default_timeout)
            user_agents = [DEFAULT_USER_AGENT]
            if rule.get("retry_with_browser_user_agent", True):
                user_agents.append(BROWSER_USER_AGENT)
            last_exc: Exception | None = None
            fetched = None
            for user_agent in user_agents:
                try:
                    fetched = fetch_html(url, timeout, max_bytes, user_agent)
                    break
                except Exception as exc:
                    last_exc = exc
                    category, status_code = classify_failure(exc)
                    retry_statuses = set(int(x) for x in rule.get("retry_on_http_status", []) or [])
                    if status_code not in retry_statuses:
                        break
            try:
                if fetched is None:
                    raise last_exc or RuntimeError("fetch_failed")
                html, final_url, content_type, http_status = fetched
                accessed += 1
                stat["access_success_count"] += 1
                result = extract(html, final_url, policy, rule)
                canonical = result.get("canonical_url")
                retry_canonical = bool(rule.get("retry_canonical", policy.get("retry_canonical_once", True)))
                if retry_canonical and canonical and canonical != final_url and safe_url(canonical, blocked):
                    try:
                        html2, final2, content2, status2 = fetch_html(canonical, timeout, max_bytes, DEFAULT_USER_AGENT)
                        result2 = extract(html2, final2, policy, rule)
                        if len(result2.get("candidates", [])) >= len(result.get("candidates", [])):
                            result, final_url, content_type, http_status = result2, final2, content2, status2
                    except Exception:
                        pass
                candidates = result.get("candidates", [])
                status = "found" if candidates else "not_found"
                item["original_date_metadata"] = {
                    "checked_at": now_iso(), "status": status, "requested_url": url,
                    "final_url": final_url, "content_type": content_type, "http_status": http_status,
                    "canonical_url": result.get("canonical_url"), "candidates": candidates,
                    "best_candidate": candidates[0] if candidates else None,
                    "publisher_key": key, "publisher_exception_id": exception_id, "auto_applied": False,
                }
                for row in candidates:
                    source_counts[str(row.get("source") or "unknown")] += 1
                if candidates:
                    enriched += 1
                    stat["date_found_count"] += 1
                else:
                    stat["metadata_not_found_count"] += 1
                    failure_counts["metadata_not_found"] += 1
                changed = True
            except Exception as exc:
                failed += 1
                stat["failed_count"] += 1
                category, status_code = classify_failure(exc)
                failure_counts[category] += 1
                stat["failure_categories"][category] = int(stat["failure_categories"].get(category, 0)) + 1
                item["original_date_metadata"] = {
                    "checked_at": now_iso(), "status": "failed", "requested_url": url,
                    "error": str(exc)[:240], "failure_category": category, "http_status": status_code,
                    "publisher_key": key, "publisher_exception_id": exception_id, "auto_applied": False,
                }
                failures.append({"event_id": item.get("event_id"), "publisher": display, "domain": domain, "url": url, "failure_category": category, "http_status": status_code, "exception_id": exception_id, "error": str(exc)[:240]})
                changed = True
        if changed:
            payload["original_date_enrichment"] = {"updated_at": now_iso(), "policy": policy.get("policy"), "processed_count": processed}
            write_json(path, payload)
        if processed >= limit:
            break

    publisher_rows = []
    for stat in publisher_stats.values():
        attempts = int(stat["attempted_count"])
        access_rate = round(int(stat["access_success_count"]) / max(attempts, 1) * 100, 1)
        found_rate = round(int(stat["date_found_count"]) / max(attempts, 1) * 100, 1)
        found_given_access = round(int(stat["date_found_count"]) / max(int(stat["access_success_count"]), 1) * 100, 1)
        stat.update({"access_success_rate": access_rate, "date_found_rate": found_rate, "date_found_rate_given_access": found_given_access, "health_status": health_status(attempts, access_rate, found_rate, policy)})
        publisher_rows.append(stat)
    status_rank = {name: i for i, name in enumerate((policy.get("publisher_health") or {}).get("status_order", []))}
    publisher_rows.sort(key=lambda x: (status_rank.get(x["health_status"], 99), -int(x["attempted_count"]), x["publisher_key"]))

    summary = {
        "processed_count": processed, "access_success_count": accessed, "enriched_count": enriched,
        "failed_count": failed, "skipped_count": skipped,
        "access_success_rate": round(accessed / max(processed, 1) * 100, 1),
        "date_found_rate": round(enriched / max(processed, 1) * 100, 1),
        "date_found_rate_given_access": round(enriched / max(accessed, 1) * 100, 1),
        "publisher_count": len(publisher_rows),
        "healthy_publisher_count": sum(1 for x in publisher_rows if x["health_status"] == "healthy"),
        "warning_publisher_count": sum(1 for x in publisher_rows if x["health_status"] == "warning"),
        "critical_publisher_count": sum(1 for x in publisher_rows if x["health_status"] == "critical"),
        "source_counts": dict(source_counts), "failure_category_counts": dict(failure_counts),
        "exception_applied_count": sum(1 for x in publisher_rows if x.get("exception_ids")), "auto_applied_count": 0,
    }
    status = {
        "updated_at": now_iso(), "policy": policy.get("policy", "phase8_original_news_date_enrichment_v2"),
        "summary": summary, "publishers": publisher_rows,
        "failures": failures[:int((policy.get("publisher_health") or {}).get("failure_preview_limit", 100))],
        "exceptions_path": str(EXCEPTIONS_PATH.relative_to(ROOT)),
        "notice": policy.get("notice"),
    }
    write_json(ADMIN_OUT, status)
    write_json(ANALYSIS_OUT, status)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

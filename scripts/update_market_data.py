#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HESEB Livestock Terminal automated data updater.

Runs in GitHub Actions and refreshes the static JSON files consumed by GitHub Pages.
No external Python packages are required.
"""
from __future__ import annotations

import email.utils
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
EVENTS = DATA / "events"
KST = timezone(timedelta(hours=9))
UTC = timezone.utc

USER_AGENT = "HESEB-Livestock-Terminal/1.0 (+https://heseb.github.io/listodata/)"

SPECIES = {
    "BEEF": {"name": "한우", "emoji": "🐂", "words": ["한우", "우육", "소고기", "쇠고기", "도축두수", "한우자조금", "beef"]},
    "PORK": {"name": "돈육", "emoji": "🐖", "words": ["돈육", "돼지", "한돈", "돈가", "ASF", "PED", "후지", "등심", "삼겹", "pork"]},
    "POULTRY": {"name": "계육", "emoji": "🐔", "words": ["계육", "닭", "도계", "가금", "AI", "조류인플루엔자", "육계", "chicken", "poultry"]},
    "DUCK": {"name": "오리", "emoji": "🦆", "words": ["오리", "duck"]},
    "EGG": {"name": "계란", "emoji": "🥚", "words": ["계란", "달걀", "산란계", "egg"]},
}

GOOGLE_NEWS = "https://news.google.com/rss/search?hl=ko&gl=KR&ceid=KR:ko&q="

NEWS_QUERIES = [
    "축산 시황 OR 축산물 가격 OR 축산 수급",
    "한우 시세 OR 한우 도축두수 OR 한우 가격",
    "돈육 시세 OR 한돈 가격 OR 돼지 도축 OR ASF",
    "계육 시세 OR 도계량 OR 육계 가격 OR 조류인플루엔자",
    "오리 시세 OR 오리 도축 OR 오리 AI",
    "계란 가격 OR 산란계 OR 달걀 가격",
    "구제역 OR ASF OR 조류인플루엔자 방역",
]

OFFICIAL_QUERIES = [
    "site:mafra.go.kr 농림축산식품부 축산 방역",
    "site:mafra.go.kr 구제역 OR ASF OR 조류인플루엔자",
    "site:ekape.or.kr 축산물품질평가원 축산 가격",
    "site:krei.re.kr 축산 관측 한우 돈육 계육",
]

DOC_TYPE_PATTERNS = [
    ("DISEASE", re.compile(r"AI|조류인플루엔자|ASF|구제역|PED|질병|방역|가축전염|살처분", re.I)),
    ("NOTICE", re.compile(r"고시|공고|공지|정책|지원|할당관세|수입위생|제도|법령|개정", re.I)),
    ("PRODUCT", re.compile(r"신제품|출시|런칭|브랜드|상품|메뉴|HMR|간편식|밀키트", re.I)),
    ("INDUSTRY", re.compile(r"산업|동향|업계|기업|투자|MOU|수출|유통|소비트렌드|시장", re.I)),
    ("MARKET", re.compile(r"시세|가격|경락|도축|도계|수급|공급|수요|출하|사육", re.I)),
]

@dataclass
class Item:
    title: str
    url: str
    published_at: datetime
    source: str
    query: str
    category: str


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def iso_kst(dt: datetime) -> str:
    return dt.astimezone(KST).isoformat()


def ymd(dt: datetime) -> str:
    return dt.astimezone(KST).date().isoformat()


def slug(s: str, prefix: str) -> str:
    return f"{prefix}_{hashlib.sha1(s.encode('utf-8')).hexdigest()[:10]}"


def fetch_url(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_date(raw: str | None) -> datetime:
    if not raw:
        return now_utc()
    try:
        return email.utils.parsedate_to_datetime(raw).astimezone(UTC)
    except Exception:
        return now_utc()


def clean_title(title: str) -> str:
    title = html.unescape(title or "").strip()
    title = re.sub(r"\s+", " ", title)
    return title


def normalize_title(title: str) -> str:
    s = clean_title(title).lower()
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", s)
    s = re.sub(r"[\s·ㆍ:：,.'\"“”‘’!?\-_/\\]+", "", s)
    return s[:160]


def google_feed(query: str) -> str:
    return GOOGLE_NEWS + urllib.parse.quote(query)


def fetch_rss(query: str, category: str) -> list[Item]:
    url = google_feed(query)
    try:
        raw = fetch_url(url)
    except Exception as e:
        print(f"WARN: RSS fetch failed: {query}: {e}", file=sys.stderr)
        return []
    try:
        root = ET.fromstring(raw)
    except Exception as e:
        print(f"WARN: RSS parse failed: {query}: {e}", file=sys.stderr)
        return []
    out: list[Item] = []
    for node in root.findall(".//item")[:30]:
        title = clean_title(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        pub = parse_date(node.findtext("pubDate"))
        source_node = node.find("source")
        source = clean_title(source_node.text if source_node is not None else "")
        if not title or not link:
            continue
        out.append(Item(title=title, url=link, published_at=pub, source=source, query=query, category=category))
    return out


def infer_species(title: str) -> list[str]:
    hits = []
    for code, meta in SPECIES.items():
        if any(re.search(re.escape(w), title, re.I) for w in meta["words"]):
            hits.append(code)
    return hits


def infer_tags(title: str) -> list[str]:
    tags = []
    tag_words = ["가격", "시세", "도축", "도계", "수급", "공급", "수요", "질병", "방역", "ASF", "AI", "구제역", "정책", "지원", "할당관세", "신제품"]
    for w in tag_words:
        if re.search(re.escape(w), title, re.I):
            tags.append(w)
    return tags[:6]


def infer_doc_type(title: str, query: str) -> str:
    txt = f"{title} {query}"
    for doc, pat in DOC_TYPE_PATTERNS:
        if pat.search(txt):
            return doc
    return "GENERAL"


def event_item(it: Item) -> dict:
    species = infer_species(it.title + " " + it.query)
    tags = infer_tags(it.title + " " + it.query)
    doc_type = infer_doc_type(it.title, it.query)
    base = {
        "event_id": slug(it.title + it.url, "NEWS" if it.category == "NEWS" else "OFF"),
        "date": ymd(it.published_at),
        "category": it.category,
        "severity": "MID" if doc_type in {"DISEASE", "MARKET", "NOTICE"} else "LOW",
        "species": species,
        "tags": tags,
        "doc_type": doc_type,
        "title": it.title,
        "published_at": iso(it.published_at),
    }
    if it.category == "NEWS":
        base.update({"publisher": it.source, "url": it.url})
    else:
        base.update({"subcategory": "OFFICIAL_AUTO", "region": "KR", "facts": {}, "template_id": "OFFICIAL_NOTICE", "source_title": it.source or "공식/기준자료 검색", "source_url": it.url})
    return base


def dedupe(items: Iterable[Item]) -> list[Item]:
    seen = set()
    out = []
    for it in sorted(items, key=lambda x: x.published_at, reverse=True):
        k = normalize_title(it.title) or it.url
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def score_species(items: list[dict], code: str) -> dict:
    rel = [x for x in items if code in x.get("species", [])]
    titles = " ".join(x.get("title", "") for x in rel[:20])
    disease = len([x for x in rel if x.get("doc_type") == "DISEASE"])
    market = len([x for x in rel if x.get("doc_type") == "MARKET"])
    notice = len([x for x in rel if x.get("doc_type") == "NOTICE"])
    up_words = len(re.findall(r"상승|강세|급등|부족|감소|방역|확산|확인|지원|수급", titles))
    down_words = len(re.findall(r"하락|약세|안정|증가|회복|완화", titles))
    score = min(95, max(35, 50 + disease * 5 + market * 3 + notice * 2 + up_words * 2 - down_words * 2))
    if score >= 68:
        tone, signal = "up", "상방 이슈 우세"
    elif score <= 44:
        tone, signal = "down", "하방·안정 이슈 우세"
    elif disease and market:
        tone, signal = "mixed", "질병·수급 혼조"
    else:
        tone, signal = "flat", "보합권 관찰"
    return {"rel": rel, "score": score, "tone": tone, "signal": signal, "disease": disease, "market": market, "notice": notice}


def make_dashboard(all_items: list[dict], generated: datetime) -> dict:
    species_payload = []
    parts = []
    for code, meta in SPECIES.items():
        sc = score_species(all_items, code)
        rel = sc["rel"]
        facts = []
        if sc["market"]:
            facts.append("가격·수급 관련 최신자료 확인")
        if sc["disease"]:
            facts.append("질병·방역 이슈 확인")
        if sc["notice"]:
            facts.append("정책·고시성 자료 확인")
        facts.extend([clean_title(x["title"])[:42] for x in rel[:3]])
        if not facts:
            facts = ["최근 공개자료 제한", "추가 기준자료 확인 필요"]
        if rel:
            summary = f"최근 {len(rel)}건의 공개자료에서 {meta['name']} 관련 이슈가 확인됩니다. {sc['signal']}로 분류되며, 세부 판단은 관련 자료 원문 확인이 필요합니다."
            report = f"{meta['name']}은 최근 공개자료 {len(rel)}건 기준 {sc['signal']} 흐름으로 분류됩니다. 가격·수급, 질병·방역, 정책성 자료를 함께 확인해 단기 운영 판단에 반영할 필요가 있습니다."
        else:
            summary = f"최근 자동수집 자료에서 {meta['name']} 직접 이슈는 제한적으로 확인됩니다. 공개 가격·수급 기준자료 중심의 보수적 확인이 필요합니다."
            report = f"{meta['name']}은 최신 자동수집 자료가 제한적이므로 공개 가격·수급 지표와 협력사 견적을 병행 확인하는 것이 적절합니다."
        species_payload.append({
            "id": code,
            "emoji": meta["emoji"],
            "name": meta["name"],
            "signal": sc["signal"],
            "confidence": "보통" if rel else "낮음",
            "tone": sc["tone"],
            "summary": summary,
            "facts": facts[:5],
            "indicators": [
                {"label": "최신자료", "value": f"{len(rel)}건", "trend": "확인"},
                {"label": "질병·방역", "value": f"{sc['disease']}건", "trend": "주의" if sc["disease"] else "관찰"},
                {"label": "시황·수급", "value": f"{sc['market']}건", "trend": "확인" if sc["market"] else "보조"},
            ],
            "report_sentence": report,
        })
        if rel:
            parts.append(f"{meta['name']} {sc['signal']}")
    headline = " / ".join(parts[:5]) if parts else "자동수집 기준 최근 축산 관련 공개자료가 제한적으로 확인됩니다."
    return {
        "updated_at": iso_kst(generated),
        "notice": "GitHub Actions 자동수집 결과입니다. 뉴스 검색 결과는 제목·링크 중심의 참고자료이며, 실제 거래가격과 계약조건은 거래처·규격·지역·계약 방식에 따라 달라질 수 있습니다.",
        "market_overview": {
            "headline": f"자동수집 최신자료 기준: {headline}",
            "drivers": [
                {"name": "가격·수급 뉴스", "level": 4, "memo": "시세·가격·도축·도계·수급 키워드가 포함된 최근 자료를 우선 반영합니다."},
                {"name": "질병·방역 이슈", "level": 4, "memo": "구제역·ASF·AI 등 방역 이슈는 단기 수급 변동성 요인으로 분리 표시합니다."},
                {"name": "정책·고시 변화", "level": 3, "memo": "정부 보도자료·고시·지원사업성 자료를 보조 근거로 반영합니다."},
                {"name": "최근성", "level": 5, "memo": "검색 결과의 발행일을 기준으로 최신 자료가 상단에 표시되도록 갱신합니다."},
            ],
        },
        "species": species_payload,
    }


def make_metrics(all_items: list[dict], generated: datetime) -> dict:
    species_metrics = []
    for code, meta in SPECIES.items():
        sc = score_species(all_items, code)
        species_metrics.append({
            "id": code,
            "basis_month": generated.astimezone(KST).strftime("%Y-%m-%d %H:%M KST"),
            "data_status": "OFFICIAL_FETCHED" if sc["rel"] else "FETCH_LIMITED",
            "data_status_label": "자동수집" if sc["rel"] else "수집제한",
            "data_confidence": 70 if sc["rel"] else 40,
            "signal_score": sc["score"],
            "metric_summary": f"자동수집 자료 {len(sc['rel'])}건, 질병·방역 {sc['disease']}건, 시황·수급 {sc['market']}건, 정책·고시 {sc['notice']}건 기준입니다.",
            "metrics": [
                {"label": "자동수집 자료", "value": len(sc["rel"]), "unit": "건", "change": sc["score"], "change_unit": "점", "direction": sc["tone"], "interpretation": sc["signal"], "data_status": "OFFICIAL_FETCHED" if sc["rel"] else "FETCH_LIMITED", "data_status_label": "자동수집" if sc["rel"] else "수집제한"},
                {"label": "질병·방역 자료", "value": sc["disease"], "unit": "건", "change": sc["disease"], "change_unit": "점", "direction": "up" if sc["disease"] else "flat", "interpretation": "방역 변수 확인" if sc["disease"] else "특이자료 제한", "data_status": "OFFICIAL_FETCHED", "data_status_label": "자동수집"},
                {"label": "시황·수급 자료", "value": sc["market"], "unit": "건", "change": sc["market"], "change_unit": "점", "direction": "mixed" if sc["market"] else "flat", "interpretation": "가격·수급 원문 확인 필요" if sc["market"] else "보조 확인", "data_status": "OFFICIAL_FETCHED", "data_status_label": "자동수집"},
            ],
        })
    return {
        "updated_at": iso_kst(generated),
        "data_policy": "GitHub Actions가 공개 RSS/검색 결과를 수집해 정적 JSON으로 갱신합니다. 제목 기반 자동분류이므로 원문 확인이 필요합니다.",
        "species": species_metrics,
    }


def main() -> int:
    generated = now_utc()
    news_items: list[Item] = []
    official_items: list[Item] = []
    for q in NEWS_QUERIES:
        news_items.extend(fetch_rss(q, "NEWS"))
        time.sleep(0.2)
    for q in OFFICIAL_QUERIES:
        official_items.extend(fetch_rss(q, "OFFICIAL"))
        time.sleep(0.2)

    news_items = dedupe(news_items)[:120]
    official_items = dedupe(official_items)[:80]
    news_events = [event_item(x) for x in news_items]
    official_events = [event_item(x) for x in official_items]
    all_events = sorted(news_events + official_events, key=lambda x: x.get("published_at", ""), reverse=True)

    write_json(EVENTS / "events_news.json", {"generated_at": iso(generated), "items": news_events})
    write_json(EVENTS / "events_official.json", {"generated_at": iso(generated), "items": official_events})
    write_json(DATA / "market_dashboard.json", make_dashboard(all_events, generated))
    write_json(DATA / "market_metrics.json", make_metrics(all_events, generated))
    write_json(DATA / "update_status.json", {
        "updated_at": iso_kst(generated),
        "generated_at": iso(generated),
        "status": "ok" if all_events else "limited",
        "news_count": len(news_events),
        "official_count": len(official_events),
        "total_count": len(all_events),
        "source": "GitHub Actions RSS auto updater",
        "workflow": ".github/workflows/update-market-data.yml",
        "manual_run_url": "https://github.com/HESEB/listodata/actions/workflows/update-market-data.yml",
    })
    print(f"updated: news={len(news_events)} official={len(official_events)} total={len(all_events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

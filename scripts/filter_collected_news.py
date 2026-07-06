#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Filter false positives from collected livestock news.

Main fixes:
- AI must mean avian influenza, not artificial intelligence.
- '미운 오리' and other idioms are not duck market news.
- Keep OTHER only for non-species common livestock market factors.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
EVENTS = DATA / "events"

AI_TECH_EXCLUDE = re.compile(
    r"인공지능|AI\s*(반도체|기술|플랫폼|웰니스|헬스|헬스케어|로봇|스타트업|서비스|솔루션|검색|챗봇|데이터|서버|칩|붐)|"
    r"HBM|낸드|키옥시아|KIOXIA|반도체|빅테크|엔비디아|오픈AI|머신러닝|딥러닝|스마트\s*무인|웰니스|루오리펀|애니이츠월드",
    re.I,
)
IDIOM_EXCLUDE = re.compile(r"미운\s*오리|오리\s*새끼|백조|오리발|오리무중|도널드\s*덕|덕후", re.I)
LIVESTOCK_CONTEXT = re.compile(
    r"축산|농장|사육|도축|도계|가금|방역|질병|가축|살처분|검역|이동제한|농식품부|KAHIS|"
    r"가격|시세|수급|공급|수요|출하|입식|산란계|계란|달걀|육계|닭|오리농장|오리\s*(도축|사육|가격|수급|농장)|"
    r"조류인플루엔자|고병원성|ASF|아프리카돼지열병|구제역|돼지|한돈|돈육|한우|우육|소고기|쇠고기",
    re.I,
)
AVIAN_FLU_CONTEXT = re.compile(r"조류인플루엔자|고병원성|가금|농장|방역|살처분|산란계|계란|달걀|육계|닭|오리|가축|검역|이동제한", re.I)
DUCK_CONTEXT = re.compile(r"오리\s*(농장|도축|사육|가격|수급|출하|고병원성|AI|조류인플루엔자)|가금|조류인플루엔자|고병원성|방역|살처분|도계", re.I)
COMMON_OTHER_CONTEXT = re.compile(r"수입|환율|사료|곡물|물류|소비|유통|정책|할당관세|관세|물가|장바구니|가격\s*안정|식품", re.I)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def should_drop(title: str, species: list[str]) -> bool:
    txt = title or ""
    if AI_TECH_EXCLUDE.search(txt):
        return True
    if IDIOM_EXCLUDE.search(txt):
        return True
    if re.search(r"\bAI\b", txt, re.I) and not AVIAN_FLU_CONTEXT.search(txt):
        return True
    if "DUCK" in species and not DUCK_CONTEXT.search(txt):
        return True
    if any(x in species for x in ["POULTRY", "DUCK", "EGG"]) and re.search(r"\bAI\b", txt, re.I) and not AVIAN_FLU_CONTEXT.search(txt):
        return True
    if species and not LIVESTOCK_CONTEXT.search(txt):
        return True
    return False


def normalize_species(item: dict) -> dict | None:
    item = dict(item)
    title = item.get("title", "")
    species = list(item.get("species") or [])

    if should_drop(title, species):
        return None

    # AI without bird-flu context is never poultry/duck/egg evidence.
    if re.search(r"\bAI\b", title, re.I) and not AVIAN_FLU_CONTEXT.search(title):
        species = [s for s in species if s not in {"POULTRY", "DUCK", "EGG"}]

    # '오리' only counts when it is poultry/livestock context, not idiom/company news.
    if "DUCK" in species and not DUCK_CONTEXT.search(title):
        species = [s for s in species if s != "DUCK"]

    # OTHER is not a bucket for unrelated tech/business news; keep only common market factors.
    if not species and COMMON_OTHER_CONTEXT.search(title) and LIVESTOCK_CONTEXT.search(title):
        species = ["OTHER"]
    elif not species and not COMMON_OTHER_CONTEXT.search(title):
        return None

    item["species"] = species
    item.setdefault("filter_policy", "livestock_context_v1")
    return item


def filter_file(path: Path) -> None:
    payload = read_json(path)
    items = payload.get("items", [])
    filtered = []
    seen = set()
    for item in items:
        new = normalize_species(item)
        if not new:
            continue
        key = (new.get("title"), new.get("url") or new.get("source_url"))
        if key in seen:
            continue
        seen.add(key)
        filtered.append(new)
    payload["items"] = filtered
    payload["filter_policy"] = "livestock_context_v1: exclude AI-tech, duck idioms, non-livestock items; AI accepted only with avian influenza context"
    payload["filtered_count"] = len(items) - len(filtered)
    write_json(path, payload)


def main() -> int:
    filter_file(EVENTS / "events_news.json")
    filter_file(EVENTS / "events_official.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

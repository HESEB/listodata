#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build an explainable AI-style judgment layer from existing DSS engines.

This is a synthesis layer, not an LLM and not a price-probability model.
It preserves HOLD gates from Direction Engine 2.0 and never invents confidence.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"app"/"data"
OUT=DATA/"analysis"/"ai_judgment.json"
ADMIN=DATA/"admin"/"ai_judgment.json"

def read(path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def rows(doc, key="species"):
    v=doc.get(key,[]) if isinstance(doc,dict) else []
    if isinstance(v,dict): return [dict(x,species=k) if isinstance(x,dict) else {"species":k} for k,x in v.items()]
    return [x for x in v if isinstance(x,dict)]

def idx(doc,key="species"):
    out={}
    for x in rows(doc,key):
        k=str(x.get("species") or x.get("id") or "")
        if k: out[k]=x
    return out

def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

direction=read(DATA/"analysis"/"direction_engine_v2.json",{})
recommend=read(DATA/"analysis"/"recommendation_engine.json",{})
evidence=read(DATA/"analysis"/"evidence_scores.json",{})
conflict=read(DATA/"analysis"/"conflict_report.json",{})
history=read(DATA/"analysis"/"history_prediction.json",{})

dmap=idx(direction); rmap=idx(recommend); emap=idx(evidence); cmap=idx(conflict); hmap=idx(history,"items")
species_order=["BEEF","PORK","POULTRY","DUCK","EGG"]
labels={"BEEF":"한우/우육","PORK":"돈육","POULTRY":"계육","DUCK":"오리","EGG":"계란"}
items=[]
for sp in species_order:
    d=dmap.get(sp,{})
    r=rmap.get(sp,{})
    e=emap.get(sp,{})
    c=cmap.get(sp,{})
    h=hmap.get(sp,{})
    hold=(d.get("decision_status")=="hold" or r.get("recommendation_status")=="hold" or bool(c.get("should_hold")))
    confidence=float(d.get("confidence_score") or e.get("confidence_score") or 0)
    coverage=float(d.get("coverage_score") or e.get("coverage_rate") or 0)
    direction_code=d.get("direction_code") or e.get("direction") or "hold"
    direction_label=d.get("direction_label") or e.get("status") or "판단 유보"
    action=(r.get("primary_action") or {}).get("label") or "판단 유보"
    hold_reasons=[]
    for src in (d.get("hold_reasons",[]), c.get("hold_reasons",[]), r.get("reasons",[])):
        for x in src or []:
            if x and x not in hold_reasons: hold_reasons.append(x)
    signals=[]
    for x in d.get("top_signals",[]) or []:
        name=x.get("name") or x.get("metric_id")
        val=x.get("adjusted_signal")
        if name: signals.append({"name":name,"signal":val,"reason":x.get("reason")})
    if not signals:
        breakdown=e.get("score_breakdown",{}) if isinstance(e.get("score_breakdown"),dict) else {}
        names={"price":"가격","supply":"수급/도축","disease":"질병/방역","policy":"정책/고시","news":"뉴스/수요"}
        for k,v in sorted(breakdown.items(),key=lambda kv:abs(float(kv[1] or 0)),reverse=True)[:3]:
            signals.append({"name":names.get(k,k),"signal":v,"reason":"Evidence Score 보조근거"})
    windows=h.get("windows",{}) if isinstance(h.get("windows"),dict) else {}
    trend=", ".join(f"{k} {v.get('memo','')}" for k,v in windows.items() if isinstance(v,dict) and v.get("memo"))
    if hold:
        headline=f"{labels[sp]}: 판단 유보"
        explanation="공식 수치 기반 판단 게이트를 통과하지 못해 방향과 구매행동을 확정하지 않습니다."
    else:
        headline=f"{labels[sp]}: {direction_label} / {action}"
        explanation=f"공식 수치 기반 Direction Engine은 {direction_label}으로 판단했고 Recommendation Engine은 {action}을 1차 행동으로 제시합니다."
    items.append({
        "species":sp,"label":labels[sp],"judgment_status":"hold" if hold else "ready",
        "direction_code":direction_code,"direction_label":direction_label,
        "confidence_score":confidence,"coverage_score":coverage,
        "recommended_action":action,"headline":headline,"explanation":explanation,
        "hold_reasons":hold_reasons[:5],"key_signals":signals[:3],
        "history_context":trend or "추세 참고자료 없음",
        "conflict":{"has_conflict":bool(c.get("has_conflict")),"severity":c.get("conflict_severity","none"),"axes":c.get("conflict_axes",[])},
        "guardrails":["확률값 임의 생성 금지","공식데이터 HOLD 게이트 우선","뉴스는 보조근거로만 사용","내부 재고·계약·수요 계획 미반영"]
    })

payload={
 "updated_at":now(),"policy":"phase7_ai_judgment_layer_v1",
 "engine_type":"explainable_dss_synthesis","is_llm":False,
 "notice":"Direction Engine 2.0·Recommendation Engine·Evidence·Conflict·History를 합성한 설명 레이어입니다. 가격예측 확률이나 생성형 AI 추론값을 임의 생성하지 않습니다.",
 "summary":{"species_count":len(items),"ready_count":sum(x["judgment_status"]=="ready" for x in items),"hold_count":sum(x["judgment_status"]=="hold" for x in items)},
 "species":items,
 "inputs":["direction_engine_v2.json","recommendation_engine.json","evidence_scores.json","conflict_report.json","history_prediction.json"]
}
for p in (OUT,ADMIN):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(payload["summary"],ensure_ascii=False))

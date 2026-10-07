#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 7-2: explainable AI Judgment synthesis + judgment change tracking.

This is deterministic DSS synthesis, not an LLM/probability model.
Direction Engine 2.0 HOLD gates always win.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"app"/"data"
OUT=DATA/"analysis"/"ai_judgment.json"
ADMIN=DATA/"admin"/"ai_judgment.json"
HISTORY=DATA/"history"/"ai_judgment_history.json"

def read(path, default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default

def write(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def rows(doc,key="species"):
    v=doc.get(key,[]) if isinstance(doc,dict) else []
    if isinstance(v,dict):return [dict(x,species=k) if isinstance(x,dict) else {"species":k} for k,x in v.items()]
    return [x for x in v if isinstance(x,dict)]

def idx(doc,key="species"):
    out={}
    for x in rows(doc,key):
        k=str(x.get("species") or x.get("id") or "")
        if k:out[k]=x
    return out

def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def num(v):
    try:return float(v or 0)
    except:return 0.0
def delta(a,b):return round(num(a)-num(b),1)

previous=read(OUT,{})
prevmap=idx(previous)
direction=read(DATA/"analysis"/"direction_engine_v2.json",{})
recommend=read(DATA/"analysis"/"recommendation_engine.json",{})
evidence=read(DATA/"analysis"/"evidence_scores.json",{})
conflict=read(DATA/"analysis"/"conflict_report.json",{})
history=read(DATA/"analysis"/"history_prediction.json",{})
dmap=idx(direction);rmap=idx(recommend);emap=idx(evidence);cmap=idx(conflict);hmap=idx(history,"items")
species_order=["BEEF","PORK","POULTRY","DUCK","EGG"]
labels={"BEEF":"한우/우육","PORK":"돈육","POULTRY":"계육","DUCK":"오리","EGG":"계란"}
axis_names={"price":"가격","supply":"수급/도축","disease":"질병/방역","policy":"정책/고시","news":"뉴스/수요"}
items=[]; changes=[]

for sp in species_order:
    d=dmap.get(sp,{});r=rmap.get(sp,{});e=emap.get(sp,{});c=cmap.get(sp,{});h=hmap.get(sp,{})
    prev=prevmap.get(sp,{})
    hold=(d.get("decision_status")=="hold" or r.get("recommendation_status")=="hold" or bool(c.get("should_hold")))
    confidence=num(d.get("confidence_score") if d.get("confidence_score") is not None else e.get("confidence_score"))
    coverage=num(d.get("coverage_score") if d.get("coverage_score") is not None else e.get("coverage_rate"))
    direction_code=d.get("direction_code") or e.get("direction") or "hold"
    direction_label=d.get("direction_label") or e.get("status") or "판단 유보"
    action=(r.get("primary_action") or {}).get("label") or "판단 유보"
    hold_reasons=[]
    for src in (d.get("hold_reasons",[]),c.get("hold_reasons",[]),r.get("reasons",[])):
        for x in src or []:
            if x and x not in hold_reasons:hold_reasons.append(x)

    primary=[]
    for x in d.get("top_signals",[]) or []:
        name=x.get("name") or x.get("metric_id")
        if name:primary.append({"type":"official_metric","name":name,"signal":x.get("adjusted_signal"),"reason":x.get("reason") or "Direction Engine 공식지표"})
    secondary=[]
    breakdown=e.get("score_breakdown",{}) if isinstance(e.get("score_breakdown"),dict) else {}
    for k,v in sorted(breakdown.items(),key=lambda kv:abs(num(kv[1])),reverse=True)[:3]:
        secondary.append({"type":"evidence_support","name":axis_names.get(k,k),"signal":v,"reason":"Evidence Score 보조근거"})
    signals=(primary or secondary)[:3]

    windows=h.get("windows",{}) if isinstance(h.get("windows"),dict) else {}
    trend_items=[{"window":k,"direction":v.get("direction"),"change":v.get("change"),"memo":v.get("memo")} for k,v in windows.items() if isinstance(v,dict)]
    trend=", ".join(f"{x['window']} {x['memo']}" for x in trend_items if x.get("memo")) or "추세 참고자료 없음"

    if hold:
        headline=f"{labels[sp]}: 판단 유보"
        explanation="공식 수치 기반 판단 게이트를 통과하지 못했습니다. 보조근거가 방향성을 보여도 공식 데이터 조건이 충족될 때까지 구매행동을 확정하지 않습니다."
    else:
        headline=f"{labels[sp]}: {direction_label} / {action}"
        explanation=f"공식 수치 기반 Direction Engine이 {direction_label}을 제시했고, Recommendation Engine의 1차 행동은 {action}입니다."

    status="hold" if hold else "ready"
    changed=bool(prev) and any([
        prev.get("judgment_status")!=status,
        prev.get("direction_code")!=direction_code,
        prev.get("recommended_action")!=action,
        abs(delta(confidence,prev.get("confidence_score")) )>=1,
        abs(delta(coverage,prev.get("coverage_score")) )>=1,
        (prev.get("conflict") or {}).get("severity")!=c.get("conflict_severity","none")
    ])
    change_reasons=[]
    if prev:
        if prev.get("judgment_status")!=status:change_reasons.append(f"판단상태 {prev.get('judgment_status','-')} → {status}")
        if prev.get("direction_code")!=direction_code:change_reasons.append(f"방향 {prev.get('direction_label','-')} → {direction_label}")
        if prev.get("recommended_action")!=action:change_reasons.append(f"구매행동 {prev.get('recommended_action','-')} → {action}")
        cd=delta(confidence,prev.get("confidence_score"));vd=delta(coverage,prev.get("coverage_score"))
        if abs(cd)>=1:change_reasons.append(f"신뢰도 {cd:+.1f}p")
        if abs(vd)>=1:change_reasons.append(f"커버리지 {vd:+.1f}p")
        oldsev=(prev.get("conflict") or {}).get("severity","none");newsev=c.get("conflict_severity","none")
        if oldsev!=newsev:change_reasons.append(f"충돌강도 {oldsev} → {newsev}")
    change={"changed":changed,"previous_updated_at":previous.get("updated_at"),"reasons":change_reasons or (["변화 없음"] if prev else ["최초 기록"]),"confidence_delta":delta(confidence,prev.get("confidence_score")) if prev else None,"coverage_delta":delta(coverage,prev.get("coverage_score")) if prev else None}

    item={
      "species":sp,"label":labels[sp],"judgment_status":status,"direction_code":direction_code,"direction_label":direction_label,
      "confidence_score":confidence,"coverage_score":coverage,"recommended_action":action,"headline":headline,"explanation":explanation,
      "evidence_explanation":{
        "primary_basis":primary[:3],
        "secondary_basis":secondary[:3],
        "gate":"HOLD 우선" if hold else "공식 데이터 판단 가능",
        "conflict_note":c.get("memo") or ("충돌 없음" if not c.get("has_conflict") else "상·하방 근거 충돌"),
        "why_this_action":(r.get("reasons") or [])[:3]
      },
      "hold_reasons":hold_reasons[:5],"key_signals":signals,"history_context":trend,"trend_windows":trend_items,
      "conflict":{"has_conflict":bool(c.get("has_conflict")),"severity":c.get("conflict_severity","none"),"axes":c.get("conflict_axes",[])},
      "change":change,
      "guardrails":["확률값 임의 생성 금지","공식데이터 HOLD 게이트 우선","뉴스는 보조근거로만 사용","내부 재고·계약·수요 계획 미반영"]
    }
    items.append(item)
    if changed:changes.append({"species":sp,"label":labels[sp],"reasons":change_reasons})

stamp=now()
payload={
 "updated_at":stamp,"policy":"phase7_ai_judgment_layer_v2","engine_type":"explainable_dss_synthesis","is_llm":False,
 "notice":"Direction·Recommendation·Evidence·Conflict·History를 합성하며 이전 실행 대비 판단 변화를 추적합니다. 확률값은 임의 생성하지 않습니다.",
 "summary":{"species_count":len(items),"ready_count":sum(x["judgment_status"]=="ready" for x in items),"hold_count":sum(x["judgment_status"]=="hold" for x in items),"changed_count":len(changes)},
 "changes":changes,"species":items,
 "inputs":["direction_engine_v2.json","recommendation_engine.json","evidence_scores.json","conflict_report.json","history_prediction.json"]
}
write(OUT,payload);write(ADMIN,payload)

hist=read(HISTORY,{"policy":"phase7_ai_judgment_history_v1","items":[]})
hist_items=hist.get("items",[]) if isinstance(hist.get("items"),list) else []
snapshot={"timestamp":stamp,"summary":payload["summary"],"species":[{"species":x["species"],"label":x["label"],"judgment_status":x["judgment_status"],"direction_code":x["direction_code"],"direction_label":x["direction_label"],"confidence_score":x["confidence_score"],"coverage_score":x["coverage_score"],"recommended_action":x["recommended_action"],"conflict_severity":x["conflict"]["severity"],"change":x["change"]} for x in items]}
hist_items.append(snapshot)
hist["updated_at"]=stamp;hist["policy"]="phase7_ai_judgment_history_v1";hist["notice"]="AI Judgment 실행별 판단 변화 이력. 최근 500회만 보관합니다.";hist["items"]=hist_items[-500:]
write(HISTORY,hist)
print(json.dumps(payload["summary"],ensure_ascii=False))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 7-3: build judgment transition alerts from AI Judgment history."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"app"/"data"
SRC=DATA/"analysis"/"ai_judgment.json"; HIST=DATA/"history"/"ai_judgment_history.json"
OUT=DATA/"analysis"/"ai_judgment_alerts.json"; ADMIN=DATA/"admin"/"ai_judgment_alerts.json"

def read(p,d):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return d
def write(p,d):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

cur=read(SRC,{}); hist=read(HIST,{})
alerts=[]
for x in cur.get("species",[]) or []:
    ch=x.get("change") or {}
    if not ch.get("changed"):continue
    reasons=ch.get("reasons") or []
    joined=" / ".join(reasons)
    severity="info"; category="quality_change"
    if any(k in joined for k in ["판단상태","방향 ","구매행동"]):
        severity="critical";category="decision_transition"
    elif abs(float(ch.get("coverage_delta") or 0))>=20 or abs(float(ch.get("confidence_delta") or 0))>=15 or "충돌강도" in joined:
        severity="warning";category="data_or_conflict_change"
    alerts.append({
      "id":f"{cur.get('updated_at','')}-{x.get('species','')}",
      "timestamp":cur.get("updated_at"),"species":x.get("species"),"label":x.get("label"),
      "severity":severity,"category":category,"headline":f"{x.get('label')} 판단 변화 감지",
      "reasons":reasons,"current":{"status":x.get("judgment_status"),"direction":x.get("direction_label"),"action":x.get("recommended_action"),"confidence":x.get("confidence_score"),"coverage":x.get("coverage_score"),"conflict":(x.get("conflict") or {}).get("severity")},
      "review_required":severity in ("critical","warning")
    })
rank={"critical":0,"warning":1,"info":2}
alerts.sort(key=lambda a:(rank.get(a["severity"],9),a["label"] or ""))
payload={"updated_at":now(),"policy":"phase7_judgment_alerts_v1","notice":"판단상태·방향·구매행동 전환은 Critical, 큰 품질/충돌 변화는 Warning, 기타 변화는 Info입니다.","summary":{"total":len(alerts),"critical":sum(a["severity"]=="critical" for a in alerts),"warning":sum(a["severity"]=="warning" for a in alerts),"info":sum(a["severity"]=="info" for a in alerts),"review_required":sum(a["review_required"] for a in alerts)},"alerts":alerts,"history_snapshots":len(hist.get("items",[]) or [])}
write(OUT,payload);write(ADMIN,payload);print(json.dumps(payload["summary"],ensure_ascii=False))

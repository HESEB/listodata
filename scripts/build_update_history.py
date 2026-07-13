#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append a compact operational update history record (max 100)."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'app'/'data'
ADMIN=DATA/'admin'
ANALYSIS=DATA/'analysis'
HISTORY=ADMIN/'update_history.json'


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')

def read(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def write(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    stability=read(ADMIN/'update_stability.json',{}).get('summary',{})
    fallback=read(ADMIN/'fallback_status.json',{}).get('summary',{})
    alerts=read(ADMIN/'quality_alerts.json',{}).get('summary',{})
    freshness=read(ADMIN/'freshness_alerts.json',{}).get('summary',{})
    source=read(ADMIN/'source_health.json',{}).get('summary',{})
    patch=read(ADMIN/'patch_status.json',{}).get('summary',{})
    status='success'
    if int(stability.get('fail_count') or 0)>0 or int(freshness.get('critical_count') or 0)>0:
        status='warning'
    record={
        'recorded_at':now_iso(),
        'status':status,
        'stability_score':stability.get('stability_score'),
        'quality_alerts':alerts.get('total_alerts',0),
        'critical_alerts':alerts.get('critical_count',0),
        'freshness_alerts':freshness.get('alert_count',0),
        'fallback_restored':fallback.get('restored_count',0),
        'fallback_coverage':fallback.get('coverage_rate'),
        'source_health_score':source.get('avg_health_score'),
        'patch_applied':patch.get('applied_count',0),
    }
    doc=read(HISTORY,{'policy':'phase6_update_history_v1','records':[]})
    records=doc.get('records',[]) if isinstance(doc,dict) else []
    records=[record]+records
    records=records[:100]
    success=sum(1 for x in records if x.get('status')=='success')
    payload={
        'updated_at':now_iso(),
        'policy':'phase6_update_history_v1',
        'summary':{
            'record_count':len(records),
            'success_count':success,
            'warning_count':len(records)-success,
            'success_rate':round(success/max(len(records),1)*100,1),
            'fallback_restore_total':sum(int(x.get('fallback_restored') or 0) for x in records),
            'critical_alert_total':sum(int(x.get('critical_alerts') or 0) for x in records),
        },
        'records':records,
        'notice':'최근 100회 운영 상태 스냅샷입니다. 실제 GitHub Actions 결론이 아니라 생성 리포트 기반 운영 이력입니다.'
    }
    write(HISTORY,payload)
    write(ANALYSIS/'update_history.json',payload)
    print(json.dumps(payload['summary'],ensure_ascii=False))
    return 0
if __name__=='__main__':raise SystemExit(main())

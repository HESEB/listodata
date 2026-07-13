#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final Phase 6 operational readiness audit."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'app'; DATA=APP/'data'; ADMIN=DATA/'admin'; ANALYSIS=DATA/'analysis'; WF=ROOT/'.github/workflows/update-market-data.yml'
REQUIRED_FILES=[
'scripts/check_update_stability.py','scripts/protect_fallback_data.py','scripts/build_quality_alerts.py','scripts/build_update_history.py','scripts/build_source_health.py','scripts/build_freshness_alerts.py','scripts/apply_admin_patches.py','scripts/build_operational_readiness.py',
'app/update-stability.html','app/fallback-status.html','app/quality-alerts.html','app/update-history.html','app/source-health.html','app/freshness-alerts.html','app/patch-approval.html','app/actions-guide.html','app/operations-badges.js',
'app/data/admin/approved_patches.json','app/data/admin/classification_overrides.json'
]
WORKFLOW_STEPS=['protect_fallback_data.py snapshot','update_market_data.py','apply_admin_patches.py','filter_collected_news.py','build_quality_layers.py','check_update_stability.py','protect_fallback_data.py verify','build_quality_alerts.py','build_source_health.py','build_freshness_alerts.py','build_update_history.py','build_operational_readiness.py']
OUTPUT_PATTERNS=['update_stability.json','fallback_status.json','quality_alerts.json','update_history.json','source_health.json','freshness_alerts.json','patch_status.json','operational_readiness.json']

def now_iso():return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    text=WF.read_text(encoding='utf-8') if WF.exists() else ''
    files=[]
    for rel in REQUIRED_FILES:
        p=ROOT/rel; files.append({'path':rel,'exists':p.exists(),'size_bytes':p.stat().st_size if p.exists() else 0,'status':'ok' if p.exists() and p.stat().st_size>2 else 'fail'})
    steps=[]; last=-1
    for token in WORKFLOW_STEPS:
        pos=text.find(token); ordered=pos>=0 and pos>last
        steps.append({'token':token,'found':pos>=0,'ordered':ordered,'position':pos,'status':'ok' if ordered else 'fail'})
        if pos>=0:last=pos
    outputs=[{'name':x,'in_commit_pattern':x in text,'status':'ok' if x in text else 'fail'} for x in OUTPUT_PATTERNS]
    checks=files+steps+outputs
    fail=sum(1 for x in checks if x.get('status')=='fail'); total=len(checks); score=round((total-fail)/max(total,1)*100)
    grade='ready' if fail==0 else ('watch' if score>=85 else 'risk')
    payload={'updated_at':now_iso(),'policy':'phase6_operational_readiness_v1','summary':{'total_checks':total,'pass_count':total-fail,'fail_count':fail,'readiness_score':score,'grade':grade,'label':{'ready':'운영준비 완료','watch':'보완 필요','risk':'운영 위험'}[grade]},'files':files,'workflow_steps':steps,'commit_outputs':outputs,'recommendations':([x['path']+' 확인' for x in files if x['status']=='fail']+[x['token']+' 순서/연결 확인' for x in steps if x['status']=='fail']+[x['name']+' commit pattern 추가' for x in outputs if x['status']=='fail']) or ['Phase 6 운영 안정화 구성 정상'],'notice':'Phase 6-1~6-9 핵심 파일, 워크플로 순서, 자동 커밋 산출물을 점검한 최종 운영 리포트입니다.'}
    write(ADMIN/'operational_readiness.json',payload);write(ANALYSIS/'operational_readiness.json',payload)
    print(json.dumps(payload['summary'],ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())

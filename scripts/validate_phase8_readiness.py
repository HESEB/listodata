#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate Phase 8 official-source and representative-news operational readiness."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'app'/'data'
ADMIN=DATA/'admin'
ANALYSIS=DATA/'analysis'
OUTS=[ADMIN/'phase8_readiness.json',ANALYSIS/'phase8_readiness.json']

def now_iso(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def read(path:Path,default:Any):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default
def write(path:Path,value:Any):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main()->int:
    required=[
      ('8-1','실제 공식데이터 연결','scripts/collect_real_official_sources.py'),
      ('8-2','API 설정 검증','scripts/validate_official_api_setup.py'),
      ('8-3','KOSIS 매핑 검증','scripts/validate_kosis_table_mapping.py'),
      ('8-4','KOSIS 코드 입력 화면','app/kosis-code-entry.html'),
      ('8-5','KOSIS URL 생성','scripts/build_kosis_api_urls.py'),
      ('8-6','대표뉴스 30일 제한','scripts/build_representative_news.py'),
      ('8-7','대표뉴스 날짜 검수','app/representative-news-date-review.html'),
      ('8-8','날짜 자동 추정','scripts/build_news_date_estimates.py'),
      ('8-9','원문 게시일 보강','scripts/enrich_original_news_dates.py'),
      ('8-10','언론사별 예외 처리','app/data/config/original_news_publisher_exceptions.json'),
    ]
    checks=[]
    for phase,name,path in required:
        exists=(ROOT/path).exists();checks.append({'phase':phase,'name':name,'path':path,'status':'pass' if exists else 'fail','message':'구현 파일 확인' if exists else '필수 파일 누락'})
    api=read(ADMIN/'official_api_setup_status.json',{}); amap=read(ADMIN/'kosis_table_mapping_status.json',{})
    real=read(ADMIN/'real_official_source_connections.json',{}); enrich=read(ADMIN/'original_news_date_enrichment.json',{})
    review=read(ADMIN/'representative_news_date_review.json',{}); rep=read(ADMIN/'representative_news.json',{})
    api_s=api.get('summary') or {}; map_s=amap.get('summary') or {}; real_s=real.get('summary') or {}; en_s=enrich.get('summary') or {}; rev_s=review.get('summary') or {}; rep_s=rep.get('summary') or {}
    structure_pass=all(x['status']=='pass' for x in checks)
    api_ready=int(api_s.get('ready_count') or 0); api_total=int(api_s.get('secret_count') or 3)
    map_ready=int(map_s.get('ready_mapping_count') or 0); map_total=int(map_s.get('mapping_count') or 10)
    official_ready=(api_total>0 and api_ready==api_total and map_total>0 and map_ready==map_total and str(real_s.get('status') or '') in {'ready','success'})
    workflow=(ROOT/'.github/workflows/update-market-data.yml').read_text(encoding='utf-8') if (ROOT/'.github/workflows/update-market-data.yml').exists() else ''
    required_steps=['Validate KOSIS table mappings','Build KOSIS API URL templates','Validate official API setup','Collect real official source data','Enrich original article publication dates','Build representative news and Context Filter v2','Build representative news date estimates','Merge original-page date metadata into review']
    missing_steps=[x for x in required_steps if x not in workflow]
    workflow_pass=not missing_steps
    if not structure_pass or not workflow_pass: overall='fail'
    elif official_ready: overall='ready'
    else: overall='limited'
    blockers=[]
    if map_ready<map_total:blockers.append(f'KOSIS 실제 지표 매핑 {map_ready}/{map_total}')
    if api_ready<api_total:blockers.append(f'Actions Secret 준비 {api_ready}/{api_total}')
    if not official_ready:blockers.append('실제 공식 API 응답 성공 미확인')
    if int(en_s.get('processed_count') or 0)==0:blockers.append('원문 게시일 수집 실운영 표본 없음')
    payload={
      'updated_at':now_iso(),'policy':'phase8_final_readiness_v1',
      'summary':{
        'overall_status':overall,'structure_status':'pass' if structure_pass else 'fail','workflow_status':'pass' if workflow_pass else 'fail',
        'official_data_status':'ready' if official_ready else 'limited','phase_count':len(checks),'phase_pass_count':sum(x['status']=='pass' for x in checks),
        'api_ready_count':api_ready,'api_total_count':api_total,'mapping_ready_count':map_ready,'mapping_total_count':map_total,
        'representative_count':int(rep_s.get('representative_count') or 0),'date_review_pending_count':int(rev_s.get('pending_count') or 0),
        'original_page_processed_count':int(en_s.get('processed_count') or 0),'original_page_enriched_count':int(en_s.get('enriched_count') or 0)
      },
      'checks':checks,'workflow':{'status':'pass' if workflow_pass else 'fail','missing_steps':missing_steps},
      'blockers':blockers,
      'next_actions':['KOSIS 통계표·항목·분류 실제 코드 입력','GitHub Actions Secret 3개 등록','Update market data 수동 실행','실제 API 응답·원문 게시일 성공률 재확인'],
      'notice':'구조 완료와 실제 데이터 운영 가능 여부를 분리합니다. Secret·통계표 코드가 없으면 LIMITED가 정상입니다.'
    }
    for path in OUTS:write(path,payload)
    print(json.dumps(payload['summary'],ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())

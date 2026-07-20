#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate Phase 10 KOSIS setup, approval, dry-run and first collection readiness."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'app'/'data'
ADMIN=DATA/'admin'
OUT_ADMIN=ADMIN/'phase10_final_validation.json'
OUT_ANALYSIS=DATA/'analysis'/'phase10_final_validation.json'

FILES={
 'preflight':ADMIN/'kosis_preflight_status.json',
 'first_run':ADMIN/'kosis_first_run_diagnostic.json',
 'candidate_review':ADMIN/'kosis_p2_p3_review.json',
 'approval_precheck':ADMIN/'kosis_approval_precheck.json',
 'approved_mapping':ADMIN/'kosis_approved_mapping_comparison.json',
 'dry_run':ADMIN/'kosis_dry_run.json',
 'promotion':ADMIN/'kosis_mapping_promotion_status.json',
 'operational_collection':ADMIN/'kosis_runtime_mapping_status.json',
 'anomaly_review':ADMIN/'kosis_first_collection_anomalies.json'
}

def read(path:Path,default:Any)->Any:
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def write(path:Path,doc:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def now()->str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')

def stage(name:str,status:str,passed:bool,blocked:bool,next_action:str,details:dict)->dict:
    return {'stage':name,'status':status,'passed':passed,'blocked':blocked,'next_action':next_action,'details':details}

def main()->int:
    docs={k:read(v,{'summary':{},'next_action':'상태 파일 생성 필요'}) for k,v in FILES.items()}
    p=docs['preflight'].get('summary') or {}; f=docs['first_run'].get('summary') or {}
    c=docs['candidate_review'].get('summary') or {}; a=docs['approval_precheck'].get('summary') or {}
    m=docs['approved_mapping'].get('summary') or {}; d=docs['dry_run'].get('summary') or {}
    pr=docs['promotion'].get('summary') or {}; r=docs['operational_collection'].get('summary') or {}
    an=docs['anomaly_review'].get('summary') or {}

    secret=bool(p.get('secret_configured') or f.get('secret_configured'))
    stages=[]
    stages.append(stage('preflight',str(p.get('status') or 'unknown'),secret and bool(p.get('repository_ready')) and bool(p.get('workflow_ready')),not secret,docs['preflight'].get('next_action','KOSIS_API_KEY 등록'),{'secret_configured':secret,'repository_ready':bool(p.get('repository_ready')),'workflow_ready':bool(p.get('workflow_ready'))}))
    first_ok=str(f.get('status')) in {'candidate_review_required','first_run_success','research_started'} or int(f.get('metric_candidate_count') or 0)>0
    stages.append(stage('first_run',str(f.get('status') or 'unknown'),first_ok,secret and not first_ok,docs['first_run'].get('next_action','Update market data 실행'),{'catalog_rows':int(f.get('catalog_row_count') or 0),'detail_rows':int(f.get('detail_row_count') or 0),'metric_candidates':int(f.get('metric_candidate_count') or 0)}))
    approved=int(c.get('approved_metric_count') or 0); unresolved=int(c.get('unresolved_metric_count') if c.get('unresolved_metric_count') is not None else 10)
    candidate_ok=approved==10 and unresolved==0
    stages.append(stage('candidate_review',str(c.get('status') or 'unknown'),candidate_ok,not first_ok,docs['candidate_review'].get('next_action','후보 검수'),{'approved_metric_count':approved,'unresolved_metric_count':unresolved,'conflict_metric_count':int(c.get('conflict_metric_count') or 0)}))
    precheck_ok=bool(a.get('mapping_generation_allowed'))
    stages.append(stage('approval_precheck',str(a.get('status') or 'unknown'),precheck_ok,not candidate_ok,docs['approval_precheck'].get('next_action','승인 JSON 점검'),{'mapping_generation_allowed':precheck_ok,'error_count':int(a.get('error_count') or 0),'warning_count':int(a.get('warning_count') or 0)}))
    mapping_ok=int(m.get('approved_metric_count') or 0)==10 and int(m.get('unresolved_metric_count') or 0)==0
    stages.append(stage('approved_mapping',str(m.get('status') or 'unknown'),mapping_ok,not precheck_ok,docs['approved_mapping'].get('next_action','승인 매핑 생성'),{'approved_metric_count':int(m.get('approved_metric_count') or 0),'unresolved_metric_count':int(m.get('unresolved_metric_count') or 0),'operational_difference_count':int(m.get('operational_difference_count') or 0)}))
    dry_ok=bool(d.get('dry_run_passed'))
    stages.append(stage('dry_run',str(d.get('status') or 'unknown'),dry_ok,not mapping_ok,docs['dry_run'].get('next_action','Dry Run 실행'),{'tested_table_count':int(d.get('tested_table_count') or 0),'passed_table_count':int(d.get('passed_table_count') or 0),'failed_table_count':int(d.get('failed_table_count') or 0)}))
    promoted=str(pr.get('status'))=='promoted' or str(r.get('promotion_status'))=='promoted'
    stages.append(stage('promotion',str(pr.get('status') or r.get('promotion_status') or 'unknown'),promoted,not dry_ok,'Dry Run 통과 후 운영 승격 승인',{'promotion_decision':pr.get('promotion_decision'),'operational_table_count':int(pr.get('operational_table_count') or 0)}))
    collected=promoted and str(r.get('status'))=='active' and int(r.get('successful_kosis_source_count') or 0)>=2
    stages.append(stage('operational_collection',str(r.get('status') or 'unknown'),collected,not promoted,'Update market data 실행 후 KOSIS 2개 소스 성공 확인',{'mapping_source':r.get('mapping_source'),'successful_kosis_source_count':int(r.get('successful_kosis_source_count') or 0),'runtime_url_count':int(r.get('runtime_url_count') or 0)}))
    anomaly_ok=str(an.get('status'))=='passed'
    stages.append(stage('anomaly_review',str(an.get('status') or 'unknown'),anomaly_ok,not collected,docs['anomaly_review'].get('next_action','첫 수집 이상치 검수'),{'record_count':int(an.get('record_count') or 0),'critical_count':int(an.get('critical_count') or 0),'warning_count':int(an.get('warning_count') or 0)}))

    passed=sum(1 for x in stages if x['passed']); blocked=[x for x in stages if not x['passed']]
    if passed==len(stages): final='ready'
    elif not secret: final='setup_required'
    elif any(x['stage']=='approval_precheck' and x['status']=='validation_failed' for x in stages): final='blocked'
    elif any(x['stage']=='dry_run' and x['status']=='failed' for x in stages): final='blocked'
    elif any(x['stage']=='anomaly_review' and x['status'] in {'critical_review_required','review_required'} for x in stages): final='review_required'
    else: final='in_progress'
    first_blocked=blocked[0] if blocked else None
    summary={'status':final,'stage_count':len(stages),'passed_stage_count':passed,'remaining_stage_count':len(stages)-passed,'secret_configured':secret,'approved_metric_count':approved,'unresolved_metric_count':unresolved,'dry_run_passed':dry_ok,'promotion_status':'promoted' if promoted else 'not_promoted','successful_kosis_source_count':int(r.get('successful_kosis_source_count') or 0),'anomaly_status':str(an.get('status') or 'unknown'),'source_files_modified':False}
    doc={'updated_at':now(),'policy':'phase10_kosis_final_validation_v1','summary':summary,'stages':stages,'first_blocked_stage':first_blocked,'next_action':first_blocked['next_action'] if first_blocked else 'Phase 11 공식 수치 Dashboard 연결 단계로 진행하세요.','source_paths':{k:str(v.relative_to(ROOT)) for k,v in FILES.items()},'security':{'api_key_exposed':False,'request_url_exposed':False},'notice':'Phase 10 전체 실행 상태를 통합 판정하며 원본 승인·운영·공식데이터 파일을 수정하지 않습니다.'}
    write(OUT_ADMIN,doc);write(OUT_ANALYSIS,doc);print(json.dumps(summary,ensure_ascii=False));return 0

if __name__=='__main__':raise SystemExit(main())

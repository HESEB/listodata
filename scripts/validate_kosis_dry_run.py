#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'app'/'data'
MAPPING=DATA/'config'/'kosis_table_mapping_approved.json'
URL_POLICY=DATA/'config'/'kosis_url_generator_policy.json'
DRY_POLICY=DATA/'config'/'kosis_dry_run_policy.json'
ADMIN=DATA/'admin'/'kosis_dry_run.json'
ANALYSIS=DATA/'analysis'/'kosis_dry_run.json'

def read(path, default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def write(path, doc):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def txt(v):return str(v or '').strip()
def val(row,*keys):
    for k in keys:
        if txt(row.get(k)):return txt(row.get(k))
    return ''
def rows(payload):
    if isinstance(payload,list):return [x for x in payload if isinstance(x,dict)]
    if isinstance(payload,dict):
        for k in ('data','result','rows','list'):
            if isinstance(payload.get(k),list):return [x for x in payload[k] if isinstance(x,dict)]
    return []

def main():
    key=os.environ.get('KOSIS_API_KEY','').strip()
    mapping=read(MAPPING,{'tables':[],'generation_summary':{}})
    up=read(URL_POLICY,{})
    dp=read(DRY_POLICY,{})
    active=[t for t in mapping.get('tables',[]) if isinstance(t,dict) and t.get('selected')]
    results=[]
    if not key:status='credential_required'
    elif not active:status='approved_mapping_required'
    else:
        names=up.get('parameter_names') or {}
        for table in active:
            metrics=[m for m in table.get('metric_mappings',[]) if m.get('enabled',True)]
            item_ids=sorted({txt((m.get('item_selector') or {}).get('ITM_ID')) for m in metrics if txt((m.get('item_selector') or {}).get('ITM_ID'))})
            class_ids=sorted({txt((m.get('classification_selectors') or {}).get('C1_ID')) for m in metrics if txt((m.get('classification_selectors') or {}).get('C1_ID'))})
            query=dict(up.get('static_parameters') or {})
            query.update({
                names.get('api_key','apiKey'):key,
                names.get('org_id','orgId'):table.get('org_id',''),
                names.get('table_id','tblId'):table.get('tbl_id',''),
                names.get('period','prdSe'):table.get('period',''),
                names.get('start_period','startPrdDe'):table.get('start_prd_de',''),
                names.get('end_period','endPrdDe'):table.get('end_prd_de',''),
                names.get('item_ids','itmId'):','.join(item_ids),
                names.get('class_level_1_ids','objL1'):','.join(class_ids)
            })
            result={'connection_id':table.get('connection_id'),'checks':{},'metrics':[],'errors':[]}
            try:
                req=Request(txt(up.get('endpoint'))+'?'+urlencode(query),headers={'User-Agent':'HESEB-DryRun'})
                with urlopen(req,timeout=int(dp.get('timeout_seconds') or 30)) as res:
                    data=json.loads(res.read().decode('utf-8',errors='replace'))
                found=rows(data)
                result['checks']['response_received']=True
                result['checks']['non_empty']=bool(found)
                seen=set();duplicate=0;period_ok=False;value_ok=False
                for r in found:
                    item=val(r,'ITM_ID','ITM_IDN','itmId'); cls=val(r,'C1','C1_ID','objL1'); period=val(r,'PRD_DE','PRD','TIME','period')
                    marker=(item,cls,period)
                    if marker in seen:duplicate+=1
                    seen.add(marker)
                    period_ok=period_ok or bool(period)
                    value_ok=value_ok or val(r,'DT','VALUE','data','val') not in ('','-','null','None')
                result['checks']['duplicate_free']=duplicate==0
                result['checks']['period_present']=period_ok
                result['checks']['value_present']=value_ok
                for m in metrics:
                    ei=txt((m.get('item_selector') or {}).get('ITM_ID')); ec=txt((m.get('classification_selectors') or {}).get('C1_ID'))
                    matched=[r for r in found if val(r,'ITM_ID','ITM_IDN','itmId')==ei and val(r,'C1','C1_ID','objL1')==ec]
                    expected=[txt(x) for x in m.get('unit_expectation',[]) or []]
                    observed=sorted({val(r,'UNIT_NM','UNIT','unit') for r in matched if val(r,'UNIT_NM','UNIT','unit')})
                    result['metrics'].append({'metric_id':m.get('metric_id'),'match_count':len(matched),'code_match':bool(matched),'unit_match':not expected or any(x in expected for x in observed),'observed_units':observed})
                result['checks']['code_match']=bool(result['metrics']) and all(x['code_match'] for x in result['metrics'])
                result['checks']['unit_match']=bool(result['metrics']) and all(x['unit_match'] for x in result['metrics'])
                result['row_count']=len(found)
                result['passed']=all(result['checks'].values())
            except Exception as e:
                result['checks']['response_received']=False
                result['errors']=[type(e).__name__+': '+str(e)[:180]]
                result['row_count']=0;result['passed']=False
            results.append(result)
        status='passed' if results and all(x.get('passed') for x in results) else 'failed'
    summary={'status':status,'approved_mapping_status':(mapping.get('generation_summary') or {}).get('status'),'table_count':len(active),'tested_table_count':len(results),'passed_table_count':sum(1 for x in results if x.get('passed')),'failed_table_count':sum(1 for x in results if not x.get('passed')),'dry_run_passed':bool(results) and all(x.get('passed') for x in results),'operational_mapping_modified':False,'official_data_modified':False}
    doc={'updated_at':now(),'policy':'phase10_kosis_dry_run_v1','summary':summary,'tables':results,'next_action':'Dry Run 통과 후 운영 승격 승인 단계로 진행하세요.' if summary['dry_run_passed'] else ('KOSIS_API_KEY를 등록하세요.' if status=='credential_required' else '승인 매핑과 응답 검증 오류를 수정하세요.'),'security':{'api_key_exposed':False,'request_url_exposed':False,'response_saved_raw':False},'notice':dp.get('notice')}
    write(ADMIN,doc);write(ANALYSIS,doc);print(json.dumps(summary,ensure_ascii=False));return 0

if __name__=='__main__':raise SystemExit(main())

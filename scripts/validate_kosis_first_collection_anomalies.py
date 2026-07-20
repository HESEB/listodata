#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json,re
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'app'/'data'
SOURCE=DATA/'official'/'manual'/'real_source_metrics.json'
OPERATIONAL=DATA/'config'/'kosis_table_mapping_operational.json'
APPROVED=DATA/'config'/'kosis_table_mapping_approved.json'
POLICY=DATA/'config'/'kosis_first_collection_anomaly_policy.json'
ADMIN=DATA/'admin'/'kosis_first_collection_anomalies.json'
ANALYSIS=DATA/'analysis'/'kosis_first_collection_anomalies.json'

def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def read(path:Path,default:Any):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def write(path:Path,doc:Any):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def mapping_index(doc:dict)->dict[str,dict]:
    out={}
    for table in doc.get('tables',[]) or []:
        for metric in table.get('metric_mappings',[]) or []:
            mid=str(metric.get('metric_id') or '')
            if mid:
                out[mid]={
                    'frequency':table.get('period'),
                    'units':[str(x) for x in metric.get('unit_expectation',[]) or []],
                    'species':metric.get('species'),
                    'selected':bool(table.get('selected'))
                }
    return out

def date_ok(value:str,frequency:str)->bool:
    value=str(value or '')
    f=str(frequency or '').upper()
    if f=='M':return bool(re.fullmatch(r'\d{4}-\d{2}',value))
    if f=='Q':return bool(re.fullmatch(r'\d{4}(?:-?Q[1-4])?',value))
    if f in {'D','DAILY'}:return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',value))
    return bool(re.fullmatch(r'\d{4}(?:-\d{2}(?:-\d{2})?)?(?:Q[1-4])?',value))

def main():
    source=read(SOURCE,{'records':[]})
    operational=read(OPERATIONAL,{'tables':[],'promotion_status':'not_promoted'})
    approved=read(APPROVED,{'tables':[]})
    policy=read(POLICY,{})
    op_index=mapping_index(operational)
    app_index=mapping_index(approved)
    use_operational=operational.get('promotion_status')=='promoted' and bool(op_index)
    idx=op_index if use_operational else app_index
    records=[x for x in source.get('records',[]) or [] if isinstance(x,dict)]
    findings=[];seen=set();series={}
    for pos,row in enumerate(records):
        mid=str(row.get('metric_id') or '')
        value=row.get('value');unit=str(row.get('unit') or '');date=str(row.get('date') or '')
        meta=idx.get(mid,{})
        key=(mid,date,unit)
        if key in seen:findings.append({'severity':'critical','type':'duplicate','metric_id':mid,'date':date,'position':pos})
        seen.add(key)
        if not isinstance(value,(int,float)):
            findings.append({'severity':'critical','type':'value_missing','metric_id':mid,'date':date,'position':pos})
        elif value<0:
            findings.append({'severity':'critical','type':'negative_value','metric_id':mid,'date':date,'value':value})
        expected_units=meta.get('units') or []
        if expected_units and unit not in expected_units:
            findings.append({'severity':'critical','type':'unit_mismatch','metric_id':mid,'date':date,'observed':unit,'expected':expected_units})
        frequency=meta.get('frequency') or row.get('frequency')
        if not date_ok(date,frequency):
            findings.append({'severity':'warning','type':'period_format','metric_id':mid,'date':date,'frequency':frequency})
        if isinstance(value,(int,float)):
            series.setdefault(mid,[]).append((date,float(value),unit))
    warn=float((policy.get('thresholds') or {}).get('warning_change_rate_pct',30))
    critical=float((policy.get('thresholds') or {}).get('critical_change_rate_pct',60))
    for mid,rows in series.items():
        rows.sort(key=lambda x:x[0])
        for prev,cur in zip(rows,rows[1:]):
            if prev[1]==0:continue
            pct=abs((cur[1]-prev[1])/prev[1]*100)
            if pct>=critical:sev='critical'
            elif pct>=warn:sev='warning'
            else:continue
            findings.append({'severity':sev,'type':'change_rate','metric_id':mid,'from_date':prev[0],'to_date':cur[0],'from_value':prev[1],'to_value':cur[1],'change_rate_pct':round(pct,2),'unit':cur[2]})
    critical_count=sum(1 for x in findings if x['severity']=='critical')
    warning_count=sum(1 for x in findings if x['severity']=='warning')
    if not records:status='collection_required'
    elif critical_count:status='critical_review_required'
    elif warning_count:status='review_required'
    else:status='passed'
    summary={
        'status':status,'record_count':len(records),'metric_count':len(series),
        'critical_count':critical_count,'warning_count':warning_count,
        'duplicate_count':sum(1 for x in findings if x['type']=='duplicate'),
        'unit_mismatch_count':sum(1 for x in findings if x['type']=='unit_mismatch'),
        'period_issue_count':sum(1 for x in findings if x['type']=='period_format'),
        'change_rate_issue_count':sum(1 for x in findings if x['type']=='change_rate'),
        'source_data_modified':False,'mapping_source':'operational' if use_operational else 'approved_fallback'
    }
    doc={'updated_at':now(),'policy':'phase10_kosis_first_collection_anomaly_v1','summary':summary,'findings':findings,'next_action':'이상치 없음. Phase 10 최종 실행검증으로 진행하세요.' if status=='passed' else ('첫 운영 수집을 실행하세요.' if status=='collection_required' else '이상 항목의 공식 KOSIS 원문·단위·기간을 관리자 검수하세요.'),'notice':policy.get('notice')}
    write(ADMIN,doc);write(ANALYSIS,doc);print(json.dumps(summary,ensure_ascii=False));return 0

if __name__=='__main__':raise SystemExit(main())

(function(){
  'use strict';
  const PATHS={
    scores:'./data/analysis/evidence_scores.json',
    chains:'./data/analysis/evidence_chains.json',
    history:'./data/analysis/history_prediction.json',
    conflicts:'./data/analysis/conflict_report.json',
    cross:'./data/analysis/cross_market_matrix.json',
    dashboard:'./data/market_dashboard.json'
  };
  const SPECIES_ORDER=['BEEF','PORK','POULTRY','DUCK','EGG','OTHER'];
  const SPECIES_LABEL={BEEF:'한우',PORK:'돈육',POULTRY:'계육',DUCK:'오리',EGG:'계란',OTHER:'공통'};
  const AXIS_LABEL={price:'가격',supply:'수급/도축',disease:'질병/방역',policy:'정책/고시',news:'뉴스/수요'};
  const esc=(s='')=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const safeArray=x=>Array.isArray(x)?x:[];
  const $=id=>document.getElementById(id);
  async function fetchJSON(url){const r=await fetch(url+'?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error(url);return r.json();}
  function addStyle(){
    if(document.getElementById('weekly-report-style'))return;
    const css=`
      .weekly-report-wrap{display:grid;gap:12px}.weekly-toolbar{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.weekly-btn{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.82);padding:8px 12px;border-radius:999px;text-decoration:none;color:#182231;font-size:12px;cursor:pointer}.weekly-btn.primary{background:linear-gradient(90deg,rgba(241,133,174,.22),rgba(107,178,255,.20));font-weight:760}.weekly-card{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.94);border-radius:20px;padding:14px;box-shadow:0 10px 24px rgba(18,28,40,.07)}.weekly-card h3{margin:0;font-size:16px}.weekly-meta{font-size:12px;color:rgba(24,34,49,.68);line-height:1.45;margin-top:5px}.weekly-pre{white-space:pre-wrap;font-family:system-ui,-apple-system,Segoe UI,Noto Sans KR,sans-serif;font-size:13px;line-height:1.65;background:rgba(255,255,255,.82);border:1px solid rgba(20,30,40,.09);border-radius:18px;padding:14px}.weekly-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}.weekly-mini{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.72);border-radius:16px;padding:11px}.weekly-mini b{font-size:13px}.weekly-mini .s{font-size:12px;color:rgba(24,34,49,.68);line-height:1.45;margin-top:5px}.weekly-badge{display:inline-flex;border:1px solid rgba(20,30,40,.09);border-radius:999px;padding:4px 7px;font-size:11px;background:rgba(255,255,255,.75);margin-right:5px}.weekly-badge.up{color:#d93c61;background:rgba(217,60,97,.08)}.weekly-badge.down{color:#2474d8;background:rgba(36,116,216,.08)}.weekly-badge.hold{color:#777;background:rgba(0,0,0,.05)}.weekly-badge.neutral{color:#c18a18;background:rgba(193,138,24,.09)}.weekly-note{font-size:12px;color:rgba(24,34,49,.72);line-height:1.55;border:1px dashed rgba(20,30,40,.09);border-radius:18px;background:rgba(255,255,255,.62);padding:12px}.report-box.weekly-hidden{display:none}
    `;
    const st=document.createElement('style');st.id='weekly-report-style';st.textContent=css;document.head.appendChild(st);
  }
  function todayKST(){try{return new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',weekday:'short'}).format(new Date());}catch(e){return new Date().toISOString().slice(0,10);}}
  function statusWord(score){const d=score?.direction;const s=score?.status||'';if(d==='hold')return '판단 유보';if(d==='up')return s||'상방 가능성';if(d==='down')return s||'하방 가능성';return s||'보합/혼조';}
  function topAxes(score){const b=score?.score_breakdown||{};return Object.entries(b).sort((a,b)=>Number(b[1])-Number(a[1])).filter(x=>Number(x[1])>0).slice(0,3).map(([k,v])=>`${AXIS_LABEL[k]||k} ${v}점`);
  }
  function trendText(pred){const p=pred?.prediction;if(!p)return '추세 데이터 누적 중';return `${p.label||'보합/혼조'}(${p.confidence||0}점)`;}
  function actionText(code,chain,score){if(chain?.purchase_action)return chain.purchase_action;const d=score?.direction||'hold';const map={
    BEEF:{up:'정육류 비축 또는 고정가 협의 검토',neutral:'명절·행사 물량 중심 선별 매입 검토',down:'필요 물량 중심 운영 검토',hold:'공식 가격·도축 자료 추가 확인'},
    PORK:{up:'후지·등심 등 하부위 비축/견적 재점검',neutral:'부위별 수요와 냉동재고 확인 후 분할 매입 검토',down:'가격 하락 확인 후 집행 검토',hold:'ASF·도축·가격 공식자료 추가 확인'},
    POULTRY:{up:'가슴살·안심·조각정육 단기 확보 검토',neutral:'도계량과 성수기 수요 확인 후 분할 확보 검토',down:'고정계약 물량 중심 운영 및 추가매입 보류 검토',hold:'도계량·AI 공식자료 추가 확인'},
    DUCK:{up:'행사물량 중심 견적 재확인 및 대체처 확보 검토',neutral:'행사수요·AI·도축량 확인 후 필요 물량 운영 검토',down:'확정 행사 물량 중심 운영 검토',hold:'오리 도축·AI 자료 보강 후 판단'},
    EGG:{up:'계란 가격·산란계·AI 이슈 확인 후 원가 영향 점검',neutral:'가격안정 정책과 산란계 흐름 관찰',down:'가격 안정 여부 확인 후 반영 검토',hold:'계란 가격·산란계 자료 추가 확인'},
    OTHER:{up:'공통 변수의 축종별 전이 가능성 확인',neutral:'수입·환율·사료·물류 보조지표 관찰',down:'공통 하방 요인 반영 여부 확인',hold:'공통자료 보강 후 판단'}
  };return (map[code]||map.OTHER)[d]||'추가 확인 필요';}
  function reasonText(score,chain,conflict){let reason=score?.reason||chain?.reason||topAxes(score).join(' + ')||'유효 근거 부족';const hold=score?.hold_decision;if(hold?.should_hold)reason+=` / 판단유보 사유: ${(hold.reasons||[]).join(', ')}`;if(score?.conflict?.has_conflict)reason+=` / 충돌축: ${(score.conflict.axes||[]).join(', ')}`;return reason;}
  function reportSentence(code,score,chain,history,conflict){const name=SPECIES_LABEL[code]||code;const status=statusWord(score);const axes=topAxes(score).join(', ')||'근거 축 누적 중';const action=actionText(code,chain,score);const reason=reasonText(score,chain,conflict);const confidence=score?.confidence_score||0;const coverage=score?.coverage_rate||0;const trend=trendText(history);
    return `[${name}]\n${name}은 ${axes} 근거를 기준으로 ${status} 신호 확인.\n- 판단근거: ${reason}\n- 신뢰도/커버리지: ${confidence}점 / ${coverage}%\n- 추세참고: ${trend}\n- 구매 검토: ${action}\n`;
  }
  function executiveSummary(scores){const valid=safeArray(scores).filter(s=>s.id!=='OTHER');const up=valid.filter(s=>s.direction==='up').map(s=>s.name);const hold=valid.filter(s=>s.direction==='hold').map(s=>s.name);const down=valid.filter(s=>s.direction==='down').map(s=>s.name);let parts=[];if(up.length)parts.push(`${up.join('·')} 상방 가능성`);if(down.length)parts.push(`${down.join('·')} 하방 가능성`);if(hold.length)parts.push(`${hold.join('·')} 판단 유보`);return parts.length?parts.join(', '):'축종별 시황은 보합/혼조 중심으로 관찰 필요';}
  function crossSummary(cross){const items=safeArray(cross?.items).slice().sort((a,b)=>Math.abs(Number(b.strength)||0)-Math.abs(Number(a.strength)||0)).slice(0,3);if(!items.length)return '축종 간 전이 영향은 추가 데이터 누적 필요';return items.map(x=>`${x.from_name}→${x.to_name} ${x.effect}(${x.strength})`).join(' / ');}
  function buildReport(data){const scores=safeArray(data.scores.species);const chainMap=Object.fromEntries(safeArray(data.chains.items).map(x=>[x.id,x]));const histMap=Object.fromEntries(safeArray(data.history.items).map(x=>[x.id,x]));const conflictMap=Object.fromEntries(safeArray(data.conflicts.species).map(x=>[x.id,x]));const lines=[];lines.push(`[주간 축산 시황 보고서 초안]`);lines.push(`작성기준: ${todayKST()}`);lines.push(``);lines.push(`■ 종합 판단`);lines.push(`- ${executiveSummary(scores)}`);lines.push(`- 축종 간 영향: ${crossSummary(data.cross)}`);lines.push(`- 본 보고서는 자동수집 공개자료 기반 참고 초안이며, 최종 보고 전 공식 지표 및 업체 견적 확인 필요.`);lines.push(``);lines.push(`■ 축종별 시황 및 구매 검토`);SPECIES_ORDER.filter(x=>x!=='OTHER').forEach(code=>{const score=scores.find(s=>s.id===code)||{id:code,name:SPECIES_LABEL[code],direction:'hold'};lines.push(reportSentence(code,score,chainMap[code],histMap[code],conflictMap[code]));});const other=scores.find(s=>s.id==='OTHER');if(other){lines.push(`[공통 변수]`);lines.push(`수입·환율·사료·물류·정책 등 공통 변수는 ${statusWord(other)} 수준으로 관찰 필요.`);lines.push(`- 판단근거: ${reasonText(other,chainMap.OTHER,conflictMap.OTHER)}`);lines.push(``);}lines.push(`■ 확인 필요사항`);lines.push(`- 가격 기준 데이터와 도축·도계량 공식자료 업데이트 여부 확인`);lines.push(`- 질병·방역 이슈 발생 시 이동제한 및 공급차질 영향 재점검`);lines.push(`- 행사/명절/성수기 운영 물량은 협력사 견적과 재고 현황 병행 검토`);return lines.join('\n');}
  function renderMini(data){const scores=safeArray(data.scores.species);return `<div class="weekly-grid">${scores.filter(s=>s.id!=='OTHER').map(s=>`<div class="weekly-mini"><b>${esc(s.name||SPECIES_LABEL[s.id]||s.id)}</b><div class="s"><span class="weekly-badge ${s.direction==='up'?'up':s.direction==='down'?'down':s.direction==='hold'?'hold':'neutral'}">${esc(statusWord(s))}</span><span class="weekly-badge">${esc(s.signal_score||0)}점</span><span class="weekly-badge">신뢰도 ${esc(s.confidence_score||0)}</span></div><div class="s">${esc(topAxes(s).join(' · ')||'근거 누적 중')}</div></div>`).join('')}</div>`;}
  function attachButtons(text){
    const copy=document.getElementById('weeklyCopy');const down=document.getElementById('weeklyDownload');const print=document.getElementById('weeklyPrint');
    if(copy)copy.onclick=async()=>{await navigator.clipboard.writeText(text);copy.textContent='복사 완료';setTimeout(()=>copy.textContent='보고서 복사',1200);};
    if(down)down.onclick=()=>{const blob=new Blob([text+'\n'],{type:'text/plain;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='weekly_livestock_market_report.txt';a.click();URL.revokeObjectURL(url);};
    if(print)print.onclick=()=>window.print();
  }
  async function run(){
    addStyle();
    const panel=document.getElementById('panel-report'); if(!panel)return;
    const box=document.getElementById('reportBox');
    try{
      const [scores,chains,history,conflicts,cross,dashboard]=await Promise.all([
        fetchJSON(PATHS.scores),fetchJSON(PATHS.chains),fetchJSON(PATHS.history).catch(()=>({items:[]})),fetchJSON(PATHS.conflicts).catch(()=>({species:[]})),fetchJSON(PATHS.cross).catch(()=>({items:[]})),fetchJSON(PATHS.dashboard).catch(()=>({}))
      ]);
      const data={scores,chains,history,conflicts,cross,dashboard};
      const text=buildReport(data);
      if(box){box.classList.add('weekly-hidden');box.textContent=text;}
      let wrap=document.getElementById('weeklyReportWrap');
      if(!wrap){wrap=document.createElement('div');wrap.id='weeklyReportWrap';wrap.className='weekly-report-wrap';const card=panel.querySelector('.card');if(card)card.appendChild(wrap);}
      wrap.innerHTML=`<div class="weekly-card"><h3>주간 시황 보고서 자동 생성</h3><div class="weekly-meta">Evidence Score·Chain·Conflict·Cross Market·History 기준으로 보고서 초안을 생성합니다.</div><div class="weekly-toolbar"><button class="weekly-btn primary" id="weeklyCopy">보고서 복사</button><button class="weekly-btn" id="weeklyDownload">TXT 다운로드</button><button class="weekly-btn" id="weeklyPrint">인쇄</button><a class="weekly-btn" href="./reasoning.html">종합근거</a></div>${renderMini(data)}</div><div class="weekly-pre" id="weeklyReportText">${esc(text)}</div><div class="weekly-note">자동 생성 초안입니다. 최종 보고 전 공식 가격·도축·질병 자료 및 협력사 견적을 확인하세요.</div>`;
      attachButtons(text);
      const title=panel.querySelector('h2'); if(title)title.textContent='주간 시황 보고서 자동 생성';
      const sub=panel.querySelector('.sub'); if(sub)sub.textContent='축종별 시장신호, 근거, 신뢰도, 구매 검토 액션을 보고서 문장으로 자동 구성합니다.';
    }catch(e){console.warn('weekly report generation failed',e);}
  }
  function boot(){setTimeout(run,800);setTimeout(run,1800);setTimeout(run,3200);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

(function(){
  'use strict';
  const SPECIES_META={BEEF:{tab:'beef',name:'한우',emoji:'🐂'},PORK:{tab:'pork',name:'돈육',emoji:'🐖'},POULTRY:{tab:'poultry',name:'계육',emoji:'🐔'},DUCK:{tab:'duck',name:'오리',emoji:'🦆'},EGG:{tab:'egg',name:'계란',emoji:'🥚'},OTHER:{tab:'other',name:'기타',emoji:'📌'}};
  const SCORE_URL='./data/analysis/evidence_scores.json';
  const CHAIN_URL='./data/analysis/evidence_chains.json';
  const HISTORY_URL='./data/analysis/history_prediction.json';
  const CONFLICT_URL='./data/analysis/conflict_report.json';
  const esc=(s='')=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const safeArray=x=>Array.isArray(x)?x:[];
  const $=id=>document.getElementById(id);
  async function fetchJSON(url){const r=await fetch(url+'?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error(url);return r.json();}
  function addStyle(){
    if(document.getElementById('decision-dashboard-style'))return;
    const css=`
      .grid.cols-auto#speciesCards{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))!important}
      .decision-card{position:relative;overflow:hidden;min-height:260px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.94);border-radius:22px;padding:14px;box-shadow:0 10px 24px rgba(18,28,40,.07);cursor:default;transition:.15s transform,.15s box-shadow}
      .decision-card:hover{transform:translateY(-2px);box-shadow:0 14px 34px rgba(18,28,40,.10)}
      .decision-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.decision-name{font-size:16px;font-weight:820}.decision-emoji{font-size:28px;line-height:1}.decision-score{font-size:28px;font-weight:860;letter-spacing:-.8px;margin-top:6px}.decision-label{display:inline-flex;align-items:center;gap:5px;padding:5px 8px;border-radius:999px;border:1px solid rgba(20,30,40,.09);font-size:11px;background:rgba(255,255,255,.72);white-space:nowrap}.decision-label.up{color:#d93c61;background:rgba(217,60,97,.08)}.decision-label.down{color:#2474d8;background:rgba(36,116,216,.08)}.decision-label.neutral{color:#c18a18;background:rgba(193,138,24,.09)}.decision-label.hold{color:#777;background:rgba(0,0,0,.05)}
      .decision-bar{height:8px;background:rgba(20,30,40,.07);border-radius:99px;overflow:hidden;margin-top:8px}.decision-bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#F185AE,#F8B871,#A573ED,#6BB2FF)}
      .decision-section{margin-top:10px;border-top:1px solid rgba(20,30,40,.09);padding-top:9px}.decision-section b{font-size:12px}.decision-text{font-size:12px;color:rgba(24,34,49,.76);line-height:1.45;margin-top:3px}.decision-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.decision-btn{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.8);border-radius:999px;padding:6px 8px;font-size:11px;text-decoration:none;color:#182231;cursor:pointer}.decision-btn.primary{background:linear-gradient(90deg,rgba(241,133,174,.18),rgba(107,178,255,.16));font-weight:760}.decision-mini{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.decision-chip{font-size:11px;padding:4px 7px;border-radius:999px;border:1px solid rgba(20,30,40,.09);background:rgba(0,0,0,.035);color:rgba(24,34,49,.68)}.decision-warning{font-size:11px;color:#c18a18;margin-top:6px}.decision-dashboard-links{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.decision-dashboard-links a{font-size:11px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.74);border-radius:999px;padding:6px 9px;text-decoration:none;color:#182231}
    `;
    const st=document.createElement('style');st.id='decision-dashboard-style';st.textContent=css;document.head.appendChild(st);
  }
  function dirClass(d){return d==='up'?'up':d==='down'?'down':d==='hold'?'hold':'neutral';}
  function labelText(score){if(score?.status)return score.status;if(score?.direction==='up')return '상방';if(score?.direction==='down')return '하방';if(score?.direction==='hold')return '판단 유보';return '보합/혼조';}
  function recommendAction(code,chain,score,pred){
    if(chain?.purchase_action)return chain.purchase_action;
    const d=score?.direction||'hold';
    const map={
      BEEF:{up:'정육류 비축 또는 고정가 협의 검토',neutral:'명절·행사 물량 중심 선별 매입',down:'필요 물량 중심 운영',hold:'공식 가격·도축 자료 추가 확인'},
      PORK:{up:'후지·등심 비축/견적 재점검',neutral:'부위별 수요와 냉동재고 확인 후 분할 매입',down:'가격 하락 확인 후 집행',hold:'ASF·도축·가격 공식자료 추가 확인'},
      POULTRY:{up:'가슴살·안심·조각정육 단기 확보 검토',neutral:'도계량과 성수기 수요 보며 분할 확보',down:'고정계약 물량 중심 운영',hold:'도계량·AI 공식자료 추가 확인'},
      DUCK:{up:'행사물량 중심 견적 재확인 및 대체처 확보',neutral:'행사수요·AI·도축량 확인 후 운영',down:'확정 물량 중심 운영',hold:'오리 도축·AI 자료 보강 후 판단'},
      EGG:{up:'계란 가격·산란계·AI 이슈 확인 후 원가 영향 점검',neutral:'가격안정 정책과 산란계 흐름 관찰',down:'가격 안정 여부 확인',hold:'계란 가격·산란계 자료 추가 확인'},
      OTHER:{up:'공통 변수의 축종별 전이 가능성 확인',neutral:'수입·환율·사료·물류 보조지표 관찰',down:'공통 하방 요인 반영 여부 확인',hold:'공통자료 보강 후 판단'}
    };
    return (map[code]||map.OTHER)[d]||'추가 확인 필요';
  }
  function whyText(score,chain,conflict,pred){
    if(chain?.reason)return chain.reason;
    if(score?.reason)return score.reason;
    const b=score?.score_breakdown||{};
    const labels=score?.score_breakdown_labels||{price:'가격',supply:'수급/도축',disease:'질병/방역',policy:'정책/고시',news:'뉴스/수요'};
    const parts=Object.entries(b).sort((a,b)=>b[1]-a[1]).slice(0,3).filter(x=>x[1]>0).map(([k,v])=>`${labels[k]||k} ${v}점`);
    return parts.length?parts.join(' + ')+' 기반':'유효 근거 부족';
  }
  function predictionChip(pred){const p=pred?.prediction;if(!p)return '';return `<span class="decision-chip">전망 ${esc(p.label||'-')}</span>`;}
  function renderCard(code,score,chain,conflict,pred,fallback){
    const meta=SPECIES_META[code]||{name:code,emoji:'📌',tab:'dashboard'};
    const signal=Number(score?.signal_score||0);
    const confidence=Number(score?.confidence_score||0);
    const coverage=Number(score?.coverage_rate||0);
    const status=labelText(score);
    const cls=dirClass(score?.direction);
    const why=whyText(score,chain,conflict,pred)||fallback?.summary||'';
    const action=recommendAction(code,chain,score,pred);
    const warning=score?.hold_decision?.should_hold?`<div class="decision-warning">판단유보: ${esc((score.hold_decision.reasons||[]).join(', ')||'근거 보강 필요')}</div>`:(score?.conflict?.has_conflict?`<div class="decision-warning">충돌주의: ${esc(score.conflict.axes?.join(', ')||score.conflict.memo||'상·하방 근거 혼재')}</div>`:'');
    const scoreWidth=Math.max(0,Math.min(100,signal));
    return `<article class="decision-card" data-tab-target="${esc(meta.tab)}">
      <div class="decision-top"><div><div class="decision-emoji">${meta.emoji}</div><div class="decision-name">${esc(meta.name)}</div></div><span class="decision-label ${cls}">${esc(status)}</span></div>
      <div class="decision-score">${signal}점</div><div class="decision-bar"><i style="width:${scoreWidth}%"></i></div>
      <div class="decision-mini"><span class="decision-chip">신뢰도 ${confidence}점</span><span class="decision-chip">커버리지 ${coverage}%</span><span class="decision-chip">근거 ${esc(score?.evidence_count||0)}건</span>${predictionChip(pred)}</div>
      <div class="decision-section"><b>왜?</b><div class="decision-text">${esc(why)}</div>${warning}</div>
      <div class="decision-section"><b>추천행동</b><div class="decision-text">${esc(action)}</div></div>
      <div class="decision-actions"><button class="decision-btn primary" data-tab-button="${esc(meta.tab)}">상세</button><a class="decision-btn" href="./score-engine.html">점수</a><a class="decision-btn" href="./evidence-chain.html">근거</a><a class="decision-btn" href="./conflict-report.html">충돌</a></div>
    </article>`;
  }
  function enhanceHeader(){
    const h=$('marketHeadline'); if(h)h.textContent='축종별 시장판단 · 근거 · 추천행동';
    const hero=document.querySelector('#panel-dashboard .hero-inner');
    if(hero&&!document.getElementById('decision-dashboard-links')){
      const div=document.createElement('div');div.id='decision-dashboard-links';div.className='decision-dashboard-links';
      div.innerHTML='<a href="./score-engine.html">Evidence Score</a><a href="./evidence-chain.html">Evidence Chain</a><a href="./conflict-report.html">Conflict</a><a href="./cross-market.html">Cross Market</a><a href="./history-prediction.html">History</a>';
      hero.appendChild(div);
    }
  }
  async function enhance(){
    addStyle();
    const box=$('speciesCards');
    if(!box)return;
    try{
      const [scores,chains,history,conflicts,dashboard]=await Promise.all([
        fetchJSON(SCORE_URL).catch(()=>({species:[]})),
        fetchJSON(CHAIN_URL).catch(()=>({items:[]})),
        fetchJSON(HISTORY_URL).catch(()=>({items:[]})),
        fetchJSON(CONFLICT_URL).catch(()=>({species:[]})),
        fetchJSON('./data/market_dashboard.json').catch(()=>({species:[]}))
      ]);
      const scoreMap=Object.fromEntries(safeArray(scores.species).map(x=>[x.id,x]));
      const chainMap=Object.fromEntries(safeArray(chains.items).map(x=>[x.id,x]));
      const predMap=Object.fromEntries(safeArray(history.items).map(x=>[x.id,x]));
      const conflictMap=Object.fromEntries(safeArray(conflicts.species).map(x=>[x.id,x]));
      const fallbackMap=Object.fromEntries(safeArray(dashboard.species).map(x=>[x.id,x]));
      const order=['BEEF','PORK','POULTRY','DUCK','EGG','OTHER'];
      box.innerHTML=order.map(code=>renderCard(code,scoreMap[code],chainMap[code],conflictMap[code],predMap[code],fallbackMap[code])).join('');
      enhanceHeader();
      box.querySelectorAll('[data-tab-button]').forEach(btn=>btn.addEventListener('click',e=>{e.stopPropagation();const tab=btn.dataset.tabButton;document.querySelector(`.tab[data-tab="${tab}"]`)?.click();}));
      box.querySelectorAll('.decision-card').forEach(card=>card.addEventListener('click',e=>{if(e.target.closest('a,button'))return;document.querySelector(`.tab[data-tab="${card.dataset.tabTarget}"]`)?.click();}));
      const updated=$('updatedAt'); if(updated&&scores.updated_at)updated.textContent='분석엔진 갱신 '+scores.updated_at;
    }catch(e){console.warn('decision dashboard enhance failed',e);}
  }
  function boot(){setTimeout(enhance,500);setTimeout(enhance,1500);setTimeout(enhance,3000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

(function(){
  'use strict';
  const SOURCE_URL='./data/source_links.json';
  const GROUP_META={
    INTELLIGENCE:{order:1,icon:'🧠',title:'시장판단 종합근거',purpose:'점수·근거체인·충돌·추세를 한 번에 확인',use:'보고 전 최종 판단 근거 확인'},
    PRICE:{order:2,icon:'💰',title:'가격 기준 데이터',purpose:'지육가·도체가격·가격 흐름 확인',use:'단가 협의와 원가 상승/하락 판단'},
    SLAUGHTER:{order:3,icon:'🏭',title:'도축·도계량 기준 데이터',purpose:'공급 가능량과 출하 흐름 확인',use:'비축·선매입 필요성 판단'},
    DISEASE:{order:4,icon:'🛡️',title:'질병·방역 공식자료',purpose:'AI·ASF·구제역 등 방역 리스크 확인',use:'이동제한·살처분·공급차질 리스크 점검'},
    POLICY:{order:5,icon:'📢',title:'정책·고시 공식자료',purpose:'정부 정책·가격안정·지원·수입 조치 확인',use:'정책성 하방/상방 요인 확인'}
  };
  const esc=(s='')=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const safeArray=x=>Array.isArray(x)?x:[];
  async function fetchJSON(url){const r=await fetch(url+'?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error(url);return r.json();}
  function addStyle(){
    if(document.getElementById('source-hub-style'))return;
    const css=`
      .source-simple-hero{border:1px solid rgba(20,30,40,.09);background:linear-gradient(160deg,rgba(241,133,174,.18),rgba(107,178,255,.14));border-radius:22px;padding:14px;margin-bottom:12px}.source-simple-title{font-size:20px;font-weight:820;letter-spacing:-.5px}.source-simple-sub{font-size:12px;color:rgba(24,34,49,.68);line-height:1.55;margin-top:6px}.source-simple-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}.source-simple-card{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.94);border-radius:20px;padding:14px;box-shadow:0 10px 24px rgba(18,28,40,.07)}.source-simple-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.source-simple-icon{font-size:26px}.source-simple-card h2{margin:0;font-size:17px}.source-purpose{font-size:13px;color:rgba(24,34,49,.82);line-height:1.45;margin-top:8px}.source-use{font-size:12px;color:#263b72;background:linear-gradient(90deg,rgba(241,133,174,.11),rgba(107,178,255,.11));border:1px solid rgba(20,30,40,.09);border-radius:14px;padding:9px;margin-top:10px}.source-links{display:flex;flex-direction:column;gap:8px;margin-top:12px}.source-link{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.72);border-radius:14px;padding:10px;text-decoration:none;color:#182231;display:block;transition:.14s transform,.14s box-shadow}.source-link:hover{transform:translateY(-2px);box-shadow:0 10px 22px rgba(18,28,40,.08)}.source-link-title{font-size:13px;font-weight:760}.source-link-meta{font-size:11px;color:rgba(24,34,49,.66);line-height:1.45;margin-top:4px}.source-chip-row{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}.source-chip{font-size:10.5px;border:1px solid rgba(20,30,40,.09);background:rgba(0,0,0,.035);color:rgba(24,34,49,.68);padding:4px 6px;border-radius:999px}.source-quick-menu{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.source-quick-menu a{font-size:11px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.78);border-radius:999px;padding:6px 9px;text-decoration:none;color:#182231}.source-empty{padding:20px;text-align:center;color:rgba(24,34,49,.68);border:1px dashed rgba(20,30,40,.09);border-radius:18px;background:rgba(255,255,255,.62)}
    `;
    const st=document.createElement('style');st.id='source-hub-style';st.textContent=css;document.head.appendChild(st);
  }
  function speciesText(arr){const m={BEEF:'한우',PORK:'돈육',POULTRY:'계육',DUCK:'오리',EGG:'계란',OTHER:'기타'};return safeArray(arr).map(x=>m[x]||x).join(' · ')||'공통';}
  function renderLink(item){const url=item.url||'#';return `<a class="source-link" href="${esc(url)}"><div class="source-link-title">${esc(item.title||'출처')}</div><div class="source-link-meta">${esc(item.provider||'')} · ${esc(item.subtitle||'')}</div><div class="source-link-meta">${esc(item.memo||'')}</div><div class="source-chip-row"><span class="source-chip">${esc(speciesText(item.species))}</span><span class="source-chip">${esc(item.id||'')}</span></div></a>`;}
  function renderGroup(group){const meta=GROUP_META[group.id]||{icon:'📌',title:group.title,purpose:group.description,use:'기준자료 확인'};return `<section class="source-simple-card" id="source-${esc(group.id)}"><div class="source-simple-top"><div><h2>${esc(meta.title||group.title)}</h2><div class="source-purpose">${esc(meta.purpose||group.description||'')}</div></div><div class="source-simple-icon">${meta.icon}</div></div><div class="source-use"><b>실무 활용</b><br>${esc(meta.use||'')}</div><div class="source-links">${safeArray(group.items).map(renderLink).join('')||'<div class="source-empty">등록된 링크 없음</div>'}</div></section>`;}
  function render(data){
    const hub=document.getElementById('sourceHub');
    if(!hub)return;
    const groups=safeArray(data.groups).slice().sort((a,b)=>(GROUP_META[a.id]?.order||99)-(GROUP_META[b.id]?.order||99));
    hub.innerHTML=`<div class="source-simple-hero"><div class="source-simple-title">공식 근거 저장소</div><div class="source-simple-sub">자료출처는 단순 링크 모음이 아니라, 시황 판단 시 무엇을 확인해야 하는지 기준을 잡는 곳입니다. 가격·도축/도계량·질병/방역·정책/고시·종합판단근거 순서로 확인합니다.</div><div class="source-quick-menu"><a href="./reasoning.html">종합판단근거</a><a href="./score-engine.html">점수근거</a><a href="./evidence-chain.html">근거체인</a><a href="./conflict-report.html">충돌검수</a><a href="./history-prediction.html">추세검수</a></div></div><div class="source-simple-grid">${groups.map(renderGroup).join('')}</div>`;
    const hero=document.querySelector('#panel-sources .hero-inner');
    if(hero){const h=hero.querySelector('.headline');if(h)h.textContent='자료출처 · 공식 근거 저장소';const s=hero.querySelector('.sub');if(s)s.textContent='가격, 도축·도계량, 질병·방역, 정책·고시, 종합판단근거를 구매 판단 순서대로 정리했습니다.';}
  }
  async function run(){addStyle();try{const data=await fetchJSON(SOURCE_URL);render(data);}catch(e){console.warn('source hub simplify failed',e);}}
  function boot(){setTimeout(run,600);setTimeout(run,1600);setTimeout(run,3000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

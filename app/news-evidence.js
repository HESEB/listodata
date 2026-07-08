(function(){
  'use strict';
  const NEWS_URL='./data/events/events_news.json';
  const OFFICIAL_URL='./data/events/events_official.json';
  const SPECIES_META={BEEF:'한우',PORK:'돈육',POULTRY:'계육',DUCK:'오리',EGG:'계란',OTHER:'기타'};
  const DOC_LABEL={NOTICE:'정책·고시',DISEASE:'질병·방역',INDUSTRY:'산업동향',PRODUCT:'신제품',MARKET:'시황·수급',GENERAL:'일반'};
  const esc=(s='')=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const safeArray=x=>Array.isArray(x)?x:[];
  async function fetchJSON(url){const r=await fetch(url+'?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error(url);return r.json();}
  function addStyle(){
    if(document.getElementById('news-evidence-style'))return;
    const css=`
      .news-evidence-badges{display:flex;gap:6px;flex-wrap:wrap;margin:7px 0}.evidence-badge{display:inline-flex;align-items:center;gap:4px;border:1px solid rgba(20,30,40,.09);border-radius:999px;padding:4px 7px;font-size:11px;background:rgba(255,255,255,.72);white-space:nowrap}.evidence-badge.up{color:#d93c61;background:rgba(217,60,97,.08)}.evidence-badge.down{color:#2474d8;background:rgba(36,116,216,.08)}.evidence-badge.neutral{color:#c18a18;background:rgba(193,138,24,.09)}.evidence-badge.type{color:#263b72;background:linear-gradient(90deg,rgba(241,133,174,.11),rgba(107,178,255,.11))}.evidence-badge.trust{color:#168a5b;background:rgba(22,138,91,.08)}.evidence-impact{letter-spacing:1px}.evidence-why{font-size:12px;color:rgba(24,34,49,.68);line-height:1.45;margin-top:5px;border-top:1px dashed rgba(20,30,40,.09);padding-top:7px}.evidence-news-toolbar{display:flex;gap:7px;flex-wrap:wrap;margin:10px 0}.evidence-news-toolbar a{font-size:11px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.74);border-radius:999px;padding:6px 9px;text-decoration:none;color:#182231}.news-card.evidence-enhanced{background:linear-gradient(180deg,rgba(255,255,255,.96),rgba(255,255,255,.88))}
    `;
    const st=document.createElement('style');st.id='news-evidence-style';st.textContent=css;document.head.appendChild(st);
  }
  function normalizeTitle(s){return String(s||'').replace(/\s+/g,' ').trim().slice(0,100);}
  function evidenceType(item){
    const t=[item.title,item.doc_type,item.evidence_type,safeArray(item.tags).join(' ')].join(' ');
    if(item.evidence_type)return item.evidence_type;
    if(/ASF|아프리카돼지열병|구제역|조류인플루엔자|고병원성|AI|방역|살처분|농장/.test(t))return '질병·방역';
    if(/도축|도계|출하|수급|공급|사육|입식|산란계|물량|재고/.test(t))return '수급·도축';
    if(/가격|시세|지육|산지|급등|하락|상승|할인|인상|인하/.test(t))return '가격';
    if(/정책|대책|지원|고시|점검|관세|가격안정|비축/.test(t))return '정책·고시';
    if(/수요|행사|명절|추석|설|복날|외식|소비|학교급식/.test(t))return '수요·행사';
    return DOC_LABEL[item.doc_type]||'일반';
  }
  function direction(item){
    const d=item.market_direction;
    if(d==='up')return ['▲ 상방','up','상방 근거'];
    if(d==='down')return ['▼ 하방','down','하방 근거'];
    const t=item.title||'';
    const up=/급등|상승|강세|부족|감소|발생|확산|방역|살처분|수급난|가격\s*인상|긴급|이동제한/.test(t);
    const down=/하락|약세|안정|할인|공급\s*확대|수입\s*증가|가격\s*인하|완화/.test(t);
    if(up&&!down)return ['▲ 상방','up','상방 근거'];
    if(down&&!up)return ['▼ 하방','down','하방 근거'];
    return ['= 중립','neutral','중립/보조'];
  }
  function sourceLevel(item){
    if(item.source_level)return [Number(item.source_level),item.source_level_label||'출처'];
    const type=item._type||item.category;
    const title=[item.publisher,item.source_title,item.title].join(' ');
    if(type==='OFFICIAL'||/농림축산식품부|KAHIS|축산물품질평가원|KREI|정부|농식품부/.test(title))return [5,'정부/공식'];
    if(/자조금|협회|농협|위원회/.test(title))return [4,'공공/협회'];
    if(item.publisher||item.source_title)return [3,'언론/자료'];
    return [1,'기타'];
  }
  function impact(item,etype,dir){
    if(item.impact_score)return Math.max(1,Math.min(5,Number(item.impact_score)||1));
    if(/질병|방역/.test(etype))return 5;
    if(/가격|수급|도축/.test(etype))return 4;
    if(/정책|고시/.test(etype))return 3;
    if(dir[1]==='neutral')return 2;
    return 3;
  }
  function speciesText(item){return safeArray(item.species).map(s=>SPECIES_META[s]||s).join('·')||'공통';}
  function evidenceMemo(item,etype,dir,level){
    const parts=[];
    parts.push(`${etype} 자료`);
    parts.push(`${dir[2]}`);
    parts.push(`출처레벨 ${level[0]}점`);
    if(item.quality_score)parts.push(`품질 ${item.quality_score}점`);
    return parts.join(' · ');
  }
  function buildMap(news,official){
    const map=new Map();
    [...safeArray(news.items).map(x=>({...x,_type:'NEWS'})),...safeArray(official.items).map(x=>({...x,_type:'OFFICIAL'}))].forEach(item=>{
      map.set(normalizeTitle(item.title),item);
    });
    return map;
  }
  function enhanceCard(card,map){
    if(card.classList.contains('evidence-enhanced'))return;
    const titleEl=card.querySelector('.news-title');
    if(!titleEl)return;
    const key=normalizeTitle(titleEl.textContent);
    const item=map.get(key)||{};
    const etype=evidenceType(item.title?item:{title:titleEl.textContent});
    const dir=direction(item.title?item:{title:titleEl.textContent});
    const lvl=sourceLevel(item);
    const imp=impact(item,etype,dir);
    const badges=document.createElement('div');
    badges.className='news-evidence-badges';
    badges.innerHTML=`<span class="evidence-badge ${dir[1]}">${dir[0]}</span><span class="evidence-badge type">${esc(etype)}</span><span class="evidence-badge trust">출처 ${lvl[0]} · ${esc(lvl[1])}</span><span class="evidence-badge"><span class="evidence-impact">${'★'.repeat(imp)}${'☆'.repeat(5-imp)}</span></span><span class="evidence-badge">${esc(speciesText(item))}</span>`;
    const why=document.createElement('div');why.className='evidence-why';why.textContent=evidenceMemo(item,etype,dir,lvl);
    titleEl.insertAdjacentElement('afterend',badges);
    card.appendChild(why);
    card.classList.add('evidence-enhanced');
  }
  function addToolbar(){
    const panel=document.getElementById('panel-news');
    if(!panel||document.getElementById('evidence-news-toolbar'))return;
    const target=panel.querySelector('.card .sub');
    if(!target)return;
    const div=document.createElement('div');div.id='evidence-news-toolbar';div.className='evidence-news-toolbar';
    div.innerHTML='<a href="./score-engine.html">점수근거</a><a href="./evidence-chain.html">인과근거</a><a href="./conflict-report.html">충돌검수</a><a href="./history-prediction.html">추세검수</a>';
    target.insertAdjacentElement('afterend',div);
  }
  async function run(){
    addStyle();
    addToolbar();
    try{
      const [news,official]=await Promise.all([fetchJSON(NEWS_URL).catch(()=>({items:[]})),fetchJSON(OFFICIAL_URL).catch(()=>({items:[]}))]);
      const map=buildMap(news,official);
      document.querySelectorAll('.news-card').forEach(card=>enhanceCard(card,map));
    }catch(e){console.warn('news evidence enhance failed',e);}
  }
  function boot(){run();setTimeout(run,700);setTimeout(run,1800);setInterval(run,3500);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

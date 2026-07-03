/* HESEB v4.1 integration layer
 * Purpose: keep v3.3 dashboard/news/report features and inject metric/score components.
 */
(function(){
  const METRICS_PATH='./data/market_metrics.json';
  const SCORE_PATH='./data/score_rules.json';
  const safe=x=>Array.isArray(x)?x:[];
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  let metrics=null, scoreRules=null;
  async function fetchJSON(p){const r=await fetch(p,{cache:'no-store'});if(!r.ok)throw new Error(p);return r.json();}
  function metricBy(id){return safe(metrics?.species).find(x=>x.id===id);}
  function unitOf(m){if(m.unit)return m.unit;if(/도계/.test(m.label))return '수';if(/도축/.test(m.label))return '두';if(/지육|가격/.test(m.label))return '원/kg';if(/수요|질병|신뢰|점수|영향/.test(m.label))return '점';return '';}
  function changeUnit(m){return m.change_unit || (m.change_label==='점수'?'점':'%');}
  function fmtChange(m){const v=Number(m.change),u=changeUnit(m);if(!Number.isFinite(v))return '-';return u==='점'?Math.round(v)+'점':(v>0?'+':'')+v.toFixed(1)+u;}
  function meaning(m){if(m.interpretation)return m.interpretation;const v=Number(m.change),u=changeUnit(m);if(!Number.isFinite(v))return '비교 기준값 추가 확보 필요';if(u==='점'){if(v>=70)return '영향도 높음';if(v>=40)return '영향도 보통';return '영향도 낮음';}if(/도축|도계|공급/.test(m.label)){if(v<=-3)return '공급 감소 신호';if(v>=3)return '공급 증가 신호';return '공급 보합권';}if(v>=3)return '가격 상승 압력 우세';if(v<=-3)return '가격 하락 압력';return '가격 보합권';}
  function cls(d){return d==='up'?'up':d==='down'?'down':d==='mixed'?'mixed':'flat';}
  function bandFor(v){const n=Number(v);return safe(scoreRules?.bands).find(b=>n>=Number(b.min)&&n<=Number(b.max));}
  function metricHTML(m){const c=cls(m.direction);return `<div class="indicator v41-metric"><span>${esc(m.label)}</span><span class="v">${esc(m.value)}${esc(unitOf(m))}</span><span class="t ${c}">${fmtChange(m)} · ${esc(meaning(m))}</span></div>`;}
  function cardMetricHTML(spId){const mt=metricBy(spId);if(!mt)return '';
    const b=bandFor(mt.signal_score);
    const rows=safe(mt.metrics).slice(0,2).map(metricHTML).join('');
    return `<div class="v41-box"><div class="v41-score"><span>시장신호 <b>${esc(mt.signal_score)}점</b></span><span>${esc(b?.label||'점수구간')}</span><span>신뢰도 <b>${esc(mt.data_confidence)}점</b></span></div>${rows}</div>`;
  }
  function detailMetricHTML(spId){const mt=metricBy(spId);if(!mt)return '';
    const b=bandFor(mt.signal_score);
    const rows=safe(mt.metrics).map(metricHTML).join('');
    const rules=safe(scoreRules?.rules).slice(0,4).map(r=>`<div class="v41-rule"><b>${esc(r.title)}</b><br><span>${esc(r.weight)}</span></div>`).join('');
    return `<div class="card mt v41-detail"><h2>v4.1 숫자 기반 핵심지표</h2><div class="sub mt">${esc(mt.basis_month||'')} 기준 · 단위·증감률·해석 통합 표시</div><div class="v41-score mt"><span>시장신호 <b>${esc(mt.signal_score)}점</b></span><span>${esc(b?.label||'점수구간')}</span><span>데이터 신뢰도 <b>${esc(mt.data_confidence)}점</b></span></div><div class="summary mt">${esc(mt.metric_summary||'')}</div><div class="mt">${rows}</div><div class="v41-explain"><b>점수 산출 근거</b><br>${esc(b?.meaning||'점수 구간 정보가 없습니다.')}</div><div class="v41-rules">${rules}</div><a class="link" href="./score.html" target="_blank" rel="noopener">전체 산식 보기 ↗</a></div>`;
  }
  function injectStyles(){if(document.getElementById('v41-style'))return;const st=document.createElement('style');st.id='v41-style';st.textContent=`
    .v41-box{margin-top:10px;border-top:1px solid var(--line);padding-top:10px}.v41-score{display:flex;gap:6px;flex-wrap:wrap}.v41-score span{font-size:11px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.72);padding:5px 8px}.v41-score b{font-size:13px}.v41-metric .t{max-width:190px;text-align:right}.v41-metric .up{color:var(--up)}.v41-metric .down{color:var(--down)}.v41-metric .flat{color:var(--flat)}.v41-metric .mixed{color:var(--mix)}.v41-detail{border-color:rgba(45,91,255,.18)}.v41-explain{font-size:12px;margin-top:10px;color:#263b72;background:linear-gradient(90deg,rgba(241,133,174,.10),rgba(107,178,255,.10));border:1px solid var(--line);border-radius:12px;padding:9px;line-height:1.5}.v41-rules{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin:10px 0}.v41-rule{font-size:12px;border:1px solid var(--line);border-radius:12px;padding:8px;background:rgba(255,255,255,.65);line-height:1.45}@media(max-width:620px){.v41-metric{grid-template-columns:1fr}.v41-metric .t{text-align:left;max-width:none}}`;
    document.head.appendChild(st);
  }
  function patchSpeciesCards(){safe(document.querySelectorAll('.species-card[data-go]')).forEach(card=>{if(card.dataset.v41==='1')return;const id=card.dataset.go;const html=cardMetricHTML(id);if(html){card.insertAdjacentHTML('beforeend',html);card.dataset.v41='1';}});}
  function patchDetails(){['BEEF','PORK','POULTRY','DUCK','EGG','OTHER'].forEach(id=>{const root=document.getElementById('detail-'+id);if(!root||root.dataset.v41==='1')return;const html=detailMetricHTML(id);if(html){root.insertAdjacentHTML('beforeend',html);root.dataset.v41='1';}});}
  function addQuickLinks(){const hub=document.getElementById('sourceQuick');if(!hub||document.getElementById('v41-quick-links'))return;const box=document.createElement('div');box.id='v41-quick-links';box.className='source-card';box.innerHTML='<div class="news-meta"><span class="badge type">v4.1</span><span>숫자·점수</span></div><div class="news-title">숫자 기반 핵심지표 / 시장신호 산식</div><div class="news-desc">v3.3의 뉴스·자료실·리포트는 유지하고 숫자 기반 판단근거를 추가로 확인합니다.</div><a class="link" href="./metrics.html" target="_blank" rel="noopener">핵심지표 보기 ↗</a><br><a class="link" href="./score.html" target="_blank" rel="noopener">산식 보기 ↗</a>';
    hub.prepend(box);
  }
  function apply(){injectStyles();patchSpeciesCards();patchDetails();addQuickLinks();}
  async function init(){try{[metrics,scoreRules]=await Promise.all([fetchJSON(METRICS_PATH),fetchJSON(SCORE_PATH)]);apply();setTimeout(apply,500);setTimeout(apply,1500);document.addEventListener('click',()=>setTimeout(apply,80),true);}catch(e){console.warn('v4.1 integration skipped',e);}}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();

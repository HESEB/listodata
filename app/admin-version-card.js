(function(){
  'use strict';
  const URL='./data/system/version.json';
  function addStyle(){
    if(document.getElementById('admin-version-card-style'))return;
    const st=document.createElement('style');
    st.id='admin-version-card-style';
    st.textContent=`
      .admin-version-card{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.82);border-radius:20px;padding:12px;margin:12px 0;box-shadow:0 10px 24px rgba(18,28,40,.06)}
      .admin-version-card h2{font-size:16px;margin:0}.admin-version-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-top:10px}.admin-version-kv{border:1px solid rgba(20,30,40,.08);background:rgba(255,255,255,.7);border-radius:14px;padding:9px}.admin-version-kv b{display:block;font-size:11px;color:rgba(24,34,49,.62);margin-bottom:3px}.admin-version-kv span{font-size:13px;font-weight:760;color:#182231}.admin-version-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.admin-version-actions a{font-size:11px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.82);border-radius:999px;padding:6px 8px;text-decoration:none;color:#182231}.admin-version-badge{display:inline-flex;border:1px solid rgba(20,30,40,.09);border-radius:999px;padding:4px 7px;font-size:11px;background:rgba(36,116,216,.08);color:#2474d8;margin-left:6px}
    `;
    document.head.appendChild(st);
  }
  const esc=(s='')=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  async function fetchJSON(path){const r=await fetch(path+'?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error(path);return r.json();}
  function kv(k,v){return `<div class="admin-version-kv"><b>${esc(k)}</b><span>${esc(v??'-')}</span></div>`;}
  async function render(){
    addStyle();
    const hero=document.querySelector('.hero .hero-inner')||document.querySelector('main');
    if(!hero||document.getElementById('admin-version-card'))return;
    const card=document.createElement('section');
    card.id='admin-version-card';
    card.className='admin-version-card';
    card.innerHTML='<h2>Version Engine <span class="admin-version-badge">로딩 중</span></h2><div class="sub mt">버전 정보를 불러오는 중...</div>';
    hero.appendChild(card);
    try{
      const v=await fetchJSON(URL);const wf=v.workflow||{};
      card.innerHTML=`<h2>Version Engine <span class="admin-version-badge">${esc(v.version||'-')}</span></h2><div class="sub mt">메인 노출 버전·빌드시간·데이터 갱신시간·Actions 상태입니다.</div><div class="admin-version-grid">${kv('Phase',v.phase)}${kv('Build',v.build_time_kst)}${kv('Data Updated',v.data_updated_at)}${kv('Actions',`${wf.name||'-'} / ${wf.status||'-'}`)}${kv('Commit',wf.commit)}${kv('Cache',v.cache_bust)}</div><div class="admin-version-actions"><a href="./version-status.html">Version 상세</a><a href="./change-log.html">변경로그</a><a href="./update-stability.html">업데이트 안정성</a></div>`;
    }catch(e){card.innerHTML=`<h2>Version Engine <span class="admin-version-badge">오류</span></h2><div class="sub mt">version.json을 불러오지 못했습니다. ${esc(String(e))}</div><div class="admin-version-actions"><a href="./version-status.html">Version 상세</a></div>`;}
  }
  function boot(){render();setTimeout(render,900);setTimeout(render,2000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

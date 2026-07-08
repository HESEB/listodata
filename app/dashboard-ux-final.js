(function(){
  'use strict';
  const ROUTE_FIXES=[
    ['./main.html#report','./report.html'],
    ['./index.html#report','./report.html'],
    ['#report','./report.html'],
    ['./main.html#sources','./source.html'],
    ['./index.html#sources','./source.html'],
    ['#sources','./source.html']
  ];
  const DUPLICATE_TEXTS=['이벤트 캘린더','시장 메모리','과거 사례 비교','자동분류 검수','규칙 테스트','변경 로그','자료출처','주간보고서'];
  function addStyle(){
    if(document.getElementById('ux-final-style'))return;
    const css=`
      .ux-final-badge{display:inline-flex;align-items:center;gap:5px;border:1px solid rgba(20,30,40,.09);background:rgba(22,138,91,.08);color:#168a5b;border-radius:999px;padding:5px 8px;font-size:11px;margin-top:8px}.ux-final-note{font-size:11px;color:rgba(24,34,49,.64);line-height:1.45;margin-top:5px}.ux-hidden-duplicate{display:none!important}
    `;
    const st=document.createElement('style');st.id='ux-final-style';st.textContent=css;document.head.appendChild(st);
  }
  function normalizeLinks(){
    document.querySelectorAll('a').forEach(a=>{
      const href=a.getAttribute('href')||'';
      ROUTE_FIXES.forEach(([from,to])=>{if(href===from)a.setAttribute('href',to);});
    });
  }
  function hideDuplicateLooseLinks(){
    const protectedSel='.dss-menu-wrap,.dss-drawer,.admin-menu-wrap,.admin-drawer,.source-actions,.quick,.toolbar';
    document.querySelectorAll('a').forEach(a=>{
      const text=(a.textContent||'').trim();
      if(!DUPLICATE_TEXTS.includes(text))return;
      if(a.closest(protectedSel))return;
      if(a.id==='dss-nav-menu')return;
      a.classList.add('ux-hidden-duplicate');
    });
  }
  function addUxBadge(){
    const hero=document.querySelector('#panel-dashboard .hero-inner');
    if(!hero||document.getElementById('ux-final-badge'))return;
    const badge=document.createElement('div');
    badge.id='ux-final-badge';
    badge.className='ux-final-badge';
    badge.textContent='UX 정리 완료 · Report/Source 단독 페이지 연결';
    const note=document.createElement('div');
    note.className='ux-final-note';
    note.textContent='구형 #report/#sources 링크는 단독 페이지로 자동 보정됩니다.';
    hero.appendChild(badge);
    hero.appendChild(note);
  }
  function redirectLegacyHash(){
    const h=(location.hash||'').replace('#','');
    if(h==='report')location.href='./report.html';
    if(h==='sources')location.href='./source.html';
  }
  function run(){addStyle();normalizeLinks();hideDuplicateLooseLinks();addUxBadge();}
  function boot(){redirectLegacyHash();run();setTimeout(run,700);setTimeout(run,1600);setTimeout(run,3200);setInterval(()=>{normalizeLinks();hideDuplicateLooseLinks();},2500);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

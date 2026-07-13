(function(){
  'use strict';
  const ADMIN_GROUPS=[
    {title:'DSS 2.0',desc:'데이터 중심 전환',items:[
      ['Phase 7 설계','./phase7-design.html','Data First 설계 기준'],
      ['공식데이터 구조','./official-data-structure.html','스키마·저장계층 검증'],
      ['공식데이터 수집','./official-data-collector.html','공식 데이터 소스별 수집 상태'],
      ['데이터 품질·커버리지','./official-data-quality.html','공식 데이터 품질·커버리지·신뢰도'],
      ['Direction Engine 2.0','./direction-engine-v2.html','공식 수치 기반 시장 방향성'],
      ['Recommendation Engine','./recommendation-engine.html','시장 방향 기반 구매 행동 추천']
    ]},
    {title:'운영상태',desc:'수집·정제·품질 현황',items:[
      ['Admin Dashboard','./admin.html','품질·필터·자료 현황'],
      ['Version 상태','./version-status.html','버전·빌드·데이터 갱신 상태'],
      ['변경 로그','./change-log.html','정책 버전·파일 상태'],
      ['자료출처','./source.html','공식 근거 저장소'],
      ['주간보고서','./report.html','시황 보고서 초안'],
      ['업데이트 안정성','./update-stability.html','자동 업데이트 점검'],
      ['Fallback 보호','./fallback-status.html','실패 시 데이터 복원 상태'],
      ['품질 경고','./quality-alerts.html','데이터 품질 경고 알림'],
      ['업데이트 이력','./update-history.html','최근 100회 운영 상태'],
      ['소스 헬스','./source-health.html','수집 소스별 성공률/기여도'],
      ['최신성 경고','./freshness-alerts.html','데이터 최신성 점검'],
      ['패치승인','./patch-approval.html','관리자 승인 패치 생성'],
      ['Actions 실행','./actions-guide.html','수동 업데이트 실행 가이드'],
      ['최종 운영점검','./operations-check.html','Phase 6 운영 준비도'],
      ['UX점검','./ux-check.html','최종 링크/메뉴 점검']
    ]},
    {title:'검수',desc:'분류 결과와 제외 자료 검토',items:[
      ['자동분류 검수','./classification-review.html','강제 포함·제외·축종 변경'],
      ['규칙 테스트','./rule-test.html','기사 제목 테스트'],
      ['Rejected 확인','./classification-review.html?status=rejected','제외 자료 우선 검토']
    ]},
    {title:'분석도구',desc:'판단 결과 검증',items:[
      ['Evidence Score','./score-engine.html','점수 구성'],
      ['Evidence Chain','./evidence-chain.html','인과 근거'],
      ['충돌검수','./conflict-report.html','상·하방 충돌'],
      ['축종간영향','./cross-market.html','대체/연관 영향']
    ]},
    {title:'전문성',desc:'시즌·과거 패턴',items:[
      ['이벤트 캘린더','./event-calendar.html','복날·명절·정책'],
      ['시장 메모리','./market-memory.html','과거 신호 변동'],
      ['과거 사례 비교','./case-comparison.html','유사사례']
    ]}
  ];
  const HIDE_TEXT=['Evidence Score 보기','분류검수','규칙테스트','변경로그'];
  function addStyle(){if(document.getElementById('admin-menu-style'))return;const css=`.admin-menu-wrap{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.80);border-radius:22px;padding:12px;margin:12px 0;box-shadow:0 10px 24px rgba(18,28,40,.06)}.admin-menu-head{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:9px}.admin-menu-title{font-size:15px;font-weight:830}.admin-menu-sub{font-size:11px;color:rgba(24,34,49,.66)}.admin-menu-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:9px}.admin-menu-group{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.72);border-radius:17px;padding:10px}.admin-menu-group h3{font-size:13px;margin:0}.admin-menu-desc{font-size:11px;color:rgba(24,34,49,.64);margin-top:3px}.admin-menu-links{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.admin-menu-links a{font-size:11px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.82);border-radius:999px;padding:6px 8px;text-decoration:none;color:#182231}.admin-menu-open{position:fixed;right:14px;bottom:14px;z-index:9999;border:1px solid rgba(20,30,40,.09);background:linear-gradient(90deg,rgba(241,133,174,.92),rgba(107,178,255,.92));color:#182231;border-radius:999px;padding:10px 13px;font-size:12px;font-weight:800;box-shadow:0 12px 26px rgba(18,28,40,.18);cursor:pointer}.admin-drawer{position:fixed;right:14px;bottom:60px;width:min(440px,calc(100vw - 28px));max-height:70vh;overflow:auto;z-index:9998;border:1px solid rgba(20,30,40,.12);background:rgba(255,255,255,.97);border-radius:22px;box-shadow:0 18px 44px rgba(18,28,40,.20);padding:13px;display:none}.admin-drawer.active{display:block}.admin-drawer .admin-menu-grid{grid-template-columns:1fr}.admin-hidden-link{display:none!important}@media(max-width:720px){.admin-menu-grid{grid-template-columns:1fr}}`;const st=document.createElement('style');st.id='admin-menu-style';st.textContent=css;document.head.appendChild(st);}
  function menuHTML(){return `<div class="admin-menu-head"><div><div class="admin-menu-title">Admin 통합 메뉴</div><div class="admin-menu-sub">DSS 2.0·운영상태·검수·분석도구·전문성</div></div></div><div class="admin-menu-grid">${ADMIN_GROUPS.map(g=>`<section class="admin-menu-group"><h3>${g.title}</h3><div class="admin-menu-desc">${g.desc}</div><div class="admin-menu-links">${g.items.map(([t,u,d])=>`<a href="${u}" title="${d}">${t}</a>`).join('')}</div></section>`).join('')}</div>`;}
  function hideNoisyLinks(){document.querySelectorAll('a,button').forEach(el=>{const text=(el.textContent||'').trim();if(HIDE_TEXT.includes(text)&&!el.closest('.admin-menu-wrap')&&!el.closest('.admin-drawer'))el.classList.add('admin-hidden-link');});}
  function addHeroMenu(){const hero=document.querySelector('.hero .hero-inner');if(!hero||document.getElementById('admin-menu-wrap'))return;const wrap=document.createElement('div');wrap.id='admin-menu-wrap';wrap.className='admin-menu-wrap';wrap.innerHTML=menuHTML();hero.appendChild(wrap);}
  function addDrawer(){if(document.getElementById('admin-menu-open'))return;const btn=document.createElement('button');btn.id='admin-menu-open';btn.className='admin-menu-open';btn.type='button';btn.textContent='Admin 메뉴';btn.onclick=toggleDrawer;const drawer=document.createElement('div');drawer.id='admin-drawer';drawer.className='admin-drawer';drawer.innerHTML=menuHTML();document.body.appendChild(drawer);document.body.appendChild(btn);}
  function addOperationsBadges(){if(document.getElementById('operations-badges-script'))return;const s=document.createElement('script');s.id='operations-badges-script';s.src='./operations-badges.js?v=phase-7-5';s.defer=true;document.body.appendChild(s);}
  function toggleDrawer(){const d=document.getElementById('admin-drawer');if(d)d.classList.toggle('active');}
  function run(){addStyle();hideNoisyLinks();addHeroMenu();addDrawer();addOperationsBadges();}
  function boot(){run();setTimeout(run,700);setTimeout(run,1600);setTimeout(run,3200);setInterval(hideNoisyLinks,2500);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

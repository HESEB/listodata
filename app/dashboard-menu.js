(function(){
  'use strict';
  const MENU_GROUPS=[
    {title:'핵심',desc:'매일 가장 먼저 확인',items:[
      ['Dashboard','./main.html','축종별 시장판단'],
      ['종합판단근거','./reasoning.html','점수·근거·구매전략'],
      ['주간보고서','./report.html','시황 보고서 초안'],
      ['자료출처','./source.html','공식 근거 저장소'],
      ['Version 상태','./version-status.html','버전·빌드·데이터 갱신 상태']
    ]},
    {title:'DSS 2.0',desc:'데이터 중심 전환',items:[
      ['Phase 7 설계','./phase7-design.html','Data First 설계 기준'],
      ['공식데이터 구조','./official-data-structure.html','스키마·저장계층 검증'],
      ['공식데이터 수집','./official-data-collector.html','공식 데이터 소스별 수집 상태'],
      ['데이터 품질·커버리지','./official-data-quality.html','공식 데이터 품질·커버리지·신뢰도'],
      ['Direction Engine 2.0','./direction-engine-v2.html','공식 수치 기반 시장 방향성']
    ]},
    {title:'분석',desc:'판단 근거 검증',items:[
      ['Evidence Score','./score-engine.html','가격·수급·질병·정책·뉴스 점수'],
      ['Evidence Chain','./evidence-chain.html','인과 흐름'],
      ['충돌검수','./conflict-report.html','상·하방 충돌'],
      ['축종간영향','./cross-market.html','대체/연관 영향'],
      ['추세검수','./history-prediction.html','7/14/30일 방향성']
    ]},
    {title:'전문성',desc:'시즌·과거 패턴',items:[
      ['이벤트 캘린더','./event-calendar.html','복날·명절·AI·정책'],
      ['시장 메모리','./market-memory.html','과거 신호 변동'],
      ['과거 사례 비교','./case-comparison.html','현재 신호 유사사례']
    ]},
    {title:'관리자',desc:'수집/분류/사전 관리',items:[
      ['Admin','./admin.html','품질·필터·상태'],
      ['분류검수','./classification-review.html','강제포함/제외/축종변경'],
      ['규칙테스트','./rule-test.html','기사 제목 테스트'],
      ['패치승인','./patch-approval.html','관리자 승인 패치 생성'],
      ['Actions 실행','./actions-guide.html','수동 업데이트 실행 가이드'],
      ['변경로그','./change-log.html','정책버전·파일상태'],
      ['업데이트 안정성','./update-stability.html','자동 업데이트 점검'],
      ['Fallback 보호','./fallback-status.html','실패 시 데이터 복원 상태'],
      ['품질 경고','./quality-alerts.html','데이터 품질 경고 알림'],
      ['업데이트 이력','./update-history.html','최근 100회 운영 상태'],
      ['소스 헬스','./source-health.html','수집 소스별 성공률/기여도'],
      ['최신성 경고','./freshness-alerts.html','데이터 최신성 점검'],
      ['최종 운영점검','./operations-check.html','Phase 6 운영 준비도'],
      ['UX점검','./ux-check.html','최종 링크/메뉴 점검']
    ]}
  ];
  const HIDE_IDS=['event-calendar-link','market-memory-link','case-comparison-link','classification-review-link','rule-test-link','change-log-link','event-calendar-nav','market-memory-nav','case-comparison-nav','classification-review-nav','rule-test-nav','change-log-nav'];
  function addStyle(){if(document.getElementById('dashboard-menu-style'))return;const css=`.dss-menu-wrap{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.78);border-radius:22px;padding:12px;margin-top:12px;box-shadow:0 10px 24px rgba(18,28,40,.06)}.dss-menu-head{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:8px}.dss-menu-title{font-size:14px;font-weight:820}.dss-menu-sub{font-size:11px;color:rgba(24,34,49,.66)}.dss-menu-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:9px}.dss-menu-group{border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.72);border-radius:17px;padding:10px}.dss-menu-group h3{font-size:13px;margin:0}.dss-menu-desc{font-size:11px;color:rgba(24,34,49,.64);margin-top:3px}.dss-menu-links{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.dss-menu-links a{font-size:11px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.82);border-radius:999px;padding:6px 8px;text-decoration:none;color:#182231}.dss-nav-menu{border:1px solid rgba(20,30,40,.09);background:linear-gradient(90deg,rgba(241,133,174,.18),rgba(107,178,255,.16));padding:8px 12px;border-radius:999px;cursor:pointer;font-size:13px;color:#182231;font-weight:760}.dss-menu-open{position:fixed;right:14px;bottom:14px;z-index:9999;border:1px solid rgba(20,30,40,.09);background:linear-gradient(90deg,rgba(241,133,174,.92),rgba(107,178,255,.92));color:#182231;border-radius:999px;padding:10px 13px;font-size:12px;font-weight:800;box-shadow:0 12px 26px rgba(18,28,40,.18);cursor:pointer}.dss-drawer{position:fixed;right:14px;bottom:60px;width:min(420px,calc(100vw - 28px));max-height:70vh;overflow:auto;z-index:9998;border:1px solid rgba(20,30,40,.12);background:rgba(255,255,255,.97);border-radius:22px;box-shadow:0 18px 44px rgba(18,28,40,.20);padding:13px;display:none}.dss-drawer.active{display:block}.dss-drawer .dss-menu-grid{grid-template-columns:1fr}@media(max-width:720px){.dss-menu-grid{grid-template-columns:1fr}}`;const st=document.createElement('style');st.id='dashboard-menu-style';st.textContent=css;document.head.appendChild(st);}
  function menuHTML(){return `<div class="dss-menu-head"><div><div class="dss-menu-title">DSS 통합 메뉴</div><div class="dss-menu-sub">핵심·DSS 2.0·분석·전문성·관리자</div></div></div><div class="dss-menu-grid">${MENU_GROUPS.map(g=>`<section class="dss-menu-group"><h3>${g.title}</h3><div class="dss-menu-desc">${g.desc}</div><div class="dss-menu-links">${g.items.map(([t,u,d])=>`<a href="${u}" title="${d}">${t}</a>`).join('')}</div></section>`).join('')}</div>`;}
  function hideOldLinks(){HIDE_IDS.forEach(id=>{const el=document.getElementById(id);if(el)el.style.display='none';});}
  function addHeroMenu(){const hero=document.querySelector('#panel-dashboard .hero-inner');if(!hero||document.getElementById('dss-menu-wrap'))return;const wrap=document.createElement('div');wrap.id='dss-menu-wrap';wrap.className='dss-menu-wrap';wrap.innerHTML=menuHTML();hero.appendChild(wrap);}
  function addNavMenu(){const nav=document.querySelector('nav');if(!nav||document.getElementById('dss-nav-menu'))return;const a=document.createElement('button');a.id='dss-nav-menu';a.className='dss-nav-menu';a.type='button';a.textContent='DSS 메뉴';a.onclick=toggleDrawer;nav.appendChild(a);}
  function addDrawer(){if(document.getElementById('dss-menu-open'))return;const btn=document.createElement('button');btn.id='dss-menu-open';btn.className='dss-menu-open';btn.type='button';btn.textContent='DSS 메뉴';btn.onclick=toggleDrawer;const drawer=document.createElement('div');drawer.id='dss-drawer';drawer.className='dss-drawer';drawer.innerHTML=menuHTML();document.body.appendChild(drawer);document.body.appendChild(btn);}
  function toggleDrawer(){const d=document.getElementById('dss-drawer');if(d)d.classList.toggle('active');}
  function run(){addStyle();hideOldLinks();addHeroMenu();addNavMenu();addDrawer();}
  function boot(){run();setTimeout(run,700);setTimeout(run,1600);setTimeout(run,3200);setInterval(hideOldLinks,2500);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

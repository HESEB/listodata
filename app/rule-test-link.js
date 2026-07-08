(function(){
  'use strict';
  function addLink(){
    const hero=document.querySelector('#panel-dashboard .hero-inner');
    if(hero&&!document.getElementById('rule-test-link')){
      const box=document.createElement('div');
      box.id='rule-test-link';
      box.style.cssText='display:flex;gap:7px;flex-wrap:wrap;margin-top:10px';
      box.innerHTML='<a href="./rule-test.html" style="font-size:11px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.76);border-radius:999px;padding:6px 9px;text-decoration:none;color:#182231">규칙 테스트</a>';
      hero.appendChild(box);
    }
    const nav=document.querySelector('nav');
    if(nav&&!document.getElementById('rule-test-nav')){
      const a=document.createElement('a');
      a.id='rule-test-nav';
      a.href='./rule-test.html';
      a.textContent='규칙테스트';
      a.style.cssText='border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.76);padding:8px 12px;border-radius:999px;cursor:pointer;font-size:13px;color:#182231;text-decoration:none';
      nav.appendChild(a);
    }
    const adminMini=document.querySelector('.mini');
    if(adminMini&&!document.getElementById('rule-test-admin-mini')){
      const br=document.createElement('br');
      const a=document.createElement('a');
      a.id='rule-test-admin-mini';
      a.className='admin-link';
      a.href='./rule-test.html';
      a.textContent='규칙테스트';
      adminMini.appendChild(br);adminMini.appendChild(a);
    }
  }
  function boot(){setTimeout(addLink,600);setTimeout(addLink,1600);setTimeout(addLink,3000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

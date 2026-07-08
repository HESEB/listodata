(function(){
  'use strict';
  function addLink(){
    const hero=document.querySelector('#panel-dashboard .hero-inner');
    if(hero&&!document.getElementById('event-calendar-link')){
      const box=document.createElement('div');
      box.id='event-calendar-link';
      box.style.cssText='display:flex;gap:7px;flex-wrap:wrap;margin-top:10px';
      box.innerHTML='<a href="./event-calendar.html" style="font-size:11px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.76);border-radius:999px;padding:6px 9px;text-decoration:none;color:#182231">이벤트 캘린더</a>';
      hero.appendChild(box);
    }
    const nav=document.querySelector('nav');
    if(nav&&!document.getElementById('event-calendar-nav')){
      const a=document.createElement('a');
      a.id='event-calendar-nav';
      a.href='./event-calendar.html';
      a.textContent='이벤트';
      a.style.cssText='border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.76);padding:8px 12px;border-radius:999px;cursor:pointer;font-size:13px;color:#182231;text-decoration:none';
      nav.appendChild(a);
    }
  }
  function boot(){setTimeout(addLink,600);setTimeout(addLink,1600);setTimeout(addLink,3000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

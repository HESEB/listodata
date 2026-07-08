(function(){
  'use strict';
  function addLink(){
    const hero=document.querySelector('#panel-dashboard .hero-inner');
    if(hero&&!document.getElementById('market-memory-link')){
      const box=document.createElement('div');
      box.id='market-memory-link';
      box.style.cssText='display:flex;gap:7px;flex-wrap:wrap;margin-top:10px';
      box.innerHTML='<a href="./market-memory.html" style="font-size:11px;border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.76);border-radius:999px;padding:6px 9px;text-decoration:none;color:#182231">시장 메모리</a>';
      hero.appendChild(box);
    }
    const nav=document.querySelector('nav');
    if(nav&&!document.getElementById('market-memory-nav')){
      const a=document.createElement('a');
      a.id='market-memory-nav';
      a.href='./market-memory.html';
      a.textContent='메모리';
      a.style.cssText='border:1px solid rgba(20,30,40,.09);background:rgba(255,255,255,.76);padding:8px 12px;border-radius:999px;cursor:pointer;font-size:13px;color:#182231;text-decoration:none';
      nav.appendChild(a);
    }
  }
  function boot(){setTimeout(addLink,600);setTimeout(addLink,1600);setTimeout(addLink,3000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

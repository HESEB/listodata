(function(){
'use strict';
function esc(s){return String(s==null?'-':s).replace(/[&<>"]/g,function(m){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]})}
function box(title,items,cls){var a=items||[];return '<div class="'+(cls||'warn')+'"><b>'+esc(title)+'</b><br>'+(a.length?a.map(function(x){return '• '+esc(x)}).join('<br>'):'• 없음')+'</div>'}
fetch('./data/analysis/ai_judgment.json?t='+Date.now(),{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
 var summary=document.getElementById('summary');if(summary)summary.textContent='READY '+(d.summary.ready_count||0)+' · HOLD '+(d.summary.hold_count||0)+' · 변화 '+(d.summary.changed_count||0)+' · '+(d.updated_at||'-');
 var cards=document.querySelectorAll('#cards .card');
 (d.species||[]).forEach(function(x,i){var card=cards[i];if(!card)return;
   var ex=x.evidence_explanation||{}, ch=x.change||{};
   var wrap=document.createElement('div');wrap.className='phase72-detail';
   var primary=(ex.primary_basis||[]).map(function(s){return (s.name||'-')+' · 신호 '+(s.signal==null?'-':s.signal)+' · '+(s.reason||'-')});
   var secondary=(ex.secondary_basis||[]).map(function(s){return (s.name||'-')+' · '+(s.signal==null?'-':s.signal)+'점'});
   wrap.innerHTML=(ch.changed?box('직전 판단 대비 변화',ch.reasons,'warn'):'<div class="sub">직전 판단 대비 핵심 변화 없음</div>')+
     '<div class="reason"><b>핵심 공식근거</b></div>'+box('Direction Engine',primary,'warn')+
     '<div class="reason"><b>보조근거</b></div>'+box('Evidence Score',secondary,'warn')+
     '<div class="sub"><b>판단 게이트:</b> '+esc(ex.gate||'-')+' · <b>7/14/30일:</b> '+esc(x.history_context||'-')+'</div>';
   card.appendChild(wrap);
 });
}).catch(function(){});
})();
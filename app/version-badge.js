(() => {
  const VERSION_URL = './data/system/version.json';
  const STATIC_VERSION_PATTERNS = [
    /v3\.3\.2/gi,
    /v4\.10(?:\.0)?/gi,
    /v6\.2\.0/gi,
    /phase-4-10/gi,
    /phase 4-10/gi,
    /ux-final-v410/gi,
    /version-engine-v620/gi
  ];

  function ensureStyle(doc) {
    if (doc.getElementById('heseb-version-badge-style')) return;
    const style = doc.createElement('style');
    style.id = 'heseb-version-badge-style';
    style.textContent = `
      .heseb-version-panel{position:fixed;right:16px;top:14px;z-index:9998;display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:999px;background:rgba(11,18,32,.86);color:#fff;box-shadow:0 10px 24px rgba(15,23,42,.18);font-size:12px;backdrop-filter:blur(10px)}
      .heseb-version-panel button{border:0;border-radius:999px;background:#fff;color:#111827;font-weight:800;font-size:11px;padding:4px 8px;cursor:pointer}
      .heseb-version-panel .muted{opacity:.72;font-weight:500}
      .heseb-version-detail{position:fixed;right:16px;top:58px;z-index:9999;width:min(380px,calc(100vw - 32px));background:#fff;border:1px solid #dbe4ee;border-radius:16px;box-shadow:0 18px 40px rgba(15,23,42,.22);padding:14px;color:#172033;font-size:13px;display:none}
      .heseb-version-detail.open{display:block}
      .heseb-version-detail h3{margin:0 0 8px;font-size:15px}
      .heseb-version-detail .row{display:flex;justify-content:space-between;gap:12px;border-top:1px solid #eef2f7;padding:7px 0}
      .heseb-version-detail .row:first-of-type{border-top:0}
      .heseb-version-detail code{font-size:11px;background:#f1f5f9;border-radius:6px;padding:2px 5px;word-break:break-all}
      .heseb-version-fixed{outline:1px dashed rgba(36,116,216,.25);outline-offset:2px}
      @media(max-width:720px){.heseb-version-panel{top:auto;bottom:72px;right:12px;max-width:calc(100vw - 24px);font-size:11px}.heseb-version-detail{top:auto;bottom:118px;right:12px}}
    `;
    doc.head.appendChild(style);
  }

  function fmt(v) {
    return v == null || v === '' ? '-' : String(v);
  }

  async function loadVersion() {
    const res = await fetch(`${VERSION_URL}?t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`version load failed: ${res.status}`);
    return res.json();
  }

  function shouldSkip(el) {
    return !el || el.closest('#heseb-version-root') || ['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT'].includes(el.tagName);
  }

  function replaceStaticVersionText(data) {
    const replacement = data.display?.short_label || data.version || 'Version';
    const phase = data.phase || replacement;
    const title = `${fmt(data.display?.build_label || data.build_time_kst)} / ${fmt(data.data_updated_at)} / cache ${fmt(data.cache_bust)}`;
    const candidates = Array.from(document.querySelectorAll('body *')).filter(el => !shouldSkip(el) && el.children.length === 0);
    candidates.forEach((el) => {
      let text = el.textContent || '';
      const original = text;
      STATIC_VERSION_PATTERNS.forEach((re) => {
        text = text.replace(re, (m) => /^phase/i.test(m) ? phase : replacement);
      });
      if (text !== original) {
        el.textContent = text;
        el.title = title;
        el.classList.add('heseb-version-fixed');
      }
    });
    Array.from(document.querySelectorAll('[title], [aria-label]')).forEach((el) => {
      if (shouldSkip(el)) return;
      ['title', 'aria-label'].forEach((attr) => {
        const val = el.getAttribute(attr);
        if (!val) return;
        let next = val;
        STATIC_VERSION_PATTERNS.forEach((re) => {
          next = next.replace(re, (m) => /^phase/i.test(m) ? phase : replacement);
        });
        if (next !== val) el.setAttribute(attr, next);
      });
    });
  }

  function render(data) {
    const doc = document;
    ensureStyle(doc);
    const old = doc.getElementById('heseb-version-root');
    if (old) old.remove();

    const root = doc.createElement('div');
    root.id = 'heseb-version-root';

    const display = data.display || {};
    const workflow = data.workflow || {};
    const counts = data.data_counts || {};
    const label = display.label || data.version || 'Version';
    const build = display.build_label || data.build_time_kst || '-';
    const cache = data.cache_bust || '-';

    root.innerHTML = `
      <div class="heseb-version-panel" title="버전·빌드·데이터 갱신 상태">
        <strong>${fmt(label)}</strong>
        <span class="muted">${fmt(workflow.status || display.status_label)}</span>
        <button type="button" data-version-toggle>상태</button>
      </div>
      <div class="heseb-version-detail" id="heseb-version-detail">
        <h3>HESEB Version Engine</h3>
        <div class="row"><b>표시 버전</b><span>${fmt(data.version)}</span></div>
        <div class="row"><b>Phase</b><span>${fmt(data.phase)}</span></div>
        <div class="row"><b>빌드시간</b><span>${fmt(build)}</span></div>
        <div class="row"><b>데이터 갱신</b><span>${fmt(data.data_updated_at)}</span></div>
        <div class="row"><b>Actions</b><span>${fmt(workflow.name)} / ${fmt(workflow.status)}</span></div>
        <div class="row"><b>Commit</b><span><code>${fmt(workflow.commit)}</code></span></div>
        <div class="row"><b>뉴스/공식</b><span>${fmt(counts.events_news)} / ${fmt(counts.events_official)}</span></div>
        <div class="row"><b>근거점수</b><span>${fmt(counts.evidence_scores)}개</span></div>
        <div class="row"><b>Cache Bust</b><span><code>${fmt(cache)}</code></span></div>
        <div class="row"><b>하드코딩 정리</b><span>자동 치환 활성</span></div>
      </div>
    `;
    doc.body.appendChild(root);

    const detail = root.querySelector('#heseb-version-detail');
    root.querySelector('[data-version-toggle]')?.addEventListener('click', () => {
      detail.classList.toggle('open');
    });

    replaceStaticVersionText(data);
    setTimeout(() => replaceStaticVersionText(data), 800);
    setTimeout(() => replaceStaticVersionText(data), 1800);
  }

  async function init() {
    try {
      const data = await loadVersion();
      render(data);
    } catch (err) {
      console.warn('Version badge failed', err);
      render({ version: 'pending', phase: 'Version Engine', display: { label: 'Version pending', status_label: '대기' }, workflow: { status: 'pending' }, cache_bust: String(Date.now()) });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

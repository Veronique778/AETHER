/* AETHER multi-platform download panel. Deliberately independent of the bundled React build.
 * This lets a static site update public release links without npm; no backend, no telemetry.
 */
(() => {
  'use strict';
  const cfg = window.AETHER_RELEASE_CHANNELS || {};
  const safeUrl = (value) => {
    try {
      const u = new URL(String(value));
      return (u.protocol === 'https:' || (u.protocol === 'http:' && ['localhost','127.0.0.1'].includes(u.hostname))) && u.hostname && !u.username && !u.password ? u.href : null;
    } catch { return null; }
  };
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  function platformCard(key, item) {
    const card = el('article','aether-platform-card');
    const heading = el('h3','aether-platform-title',item.label || key);
    const arch = el('p','aether-platform-arch', item.arch || '');
    const status = el('span','aether-platform-status',item.status === 'available' && safeUrl(item.downloadUrl) ? 'AVAILABLE' : 'COMING SOON');
    const top = el('div','aether-platform-top');top.append(heading,status);card.append(top,arch);
    card.append(el('p','aether-platform-version',item.version || ''));
    const note=el('p','aether-platform-note',item.note || '');card.append(note);
    const href = item.status === 'available' ? safeUrl(item.downloadUrl) : null;
    if (href) {
      const link = el('a','aether-platform-download','Download for ' + (item.label || key));
      link.href=href;link.target='_blank';link.rel='noopener noreferrer';
      link.dataset.platform=key;card.append(link);
      if (/^[a-f\d]{64}$/i.test(item.sha256||'')) {
        const code=el('code','aether-platform-sha','SHA-256: '+item.sha256);card.append(code);
      }
    } else {
      card.append(el('span','aether-platform-disabled','Build and verification in progress'));
    }
    return card;
  }
  function enablePrimaryDownloadLink() {
    const item = cfg.windows;
    const href = item && item.status === 'available' ? safeUrl(item.downloadUrl) : null;
    if (!href) return;
    for (const badge of document.querySelectorAll('span[role="status"]')) {
      if (!badge.textContent?.includes('Download coming soon')) continue;
      const link = el('a','cta-primary inline-flex items-center gap-2 rounded-xl border px-6 py-3.5 text-base font-semibold transition','Download AETHER for Windows');
      link.href = href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.dataset.platform = 'windows';
      badge.replaceWith(link);
    }
  }
  function mount() {
    const section = document.getElementById('download');
    if (!section || document.getElementById('aether-platforms')) return !!section;
    const wrap=el('div','aether-platforms');wrap.id='aether-platforms';
    wrap.append(el('h3','aether-platform-heading','Download AETHER for your platform'));
    wrap.append(el('p','aether-platform-intro', 'The interactive browser demo works on all devices. Native apps are published only after an operating-system build and testing.'));
    const grid=el('div','aether-platform-grid');
    for (const key of ['windows','macos','linux']) {
      if(cfg[key]) grid.append(platformCard(key,cfg[key]));
    }
    wrap.append(grid);
    enablePrimaryDownloadLink();
    // Place before the prior Windows-only release table to keep existing details accessible.
    const oldGrid=section.querySelector('.mt-10.grid');
    if (oldGrid && oldGrid.parentNode) oldGrid.parentNode.insertBefore(wrap,oldGrid);
    else section.append(wrap);
    // Avoid displaying the old pinned ZIP hash (it belongs to an older Windows BLE build).
    const oldChecksum=section.querySelector('[data-testid="sha256"]');
    if (oldChecksum) {
      const row=oldChecksum.closest('div');if(row)row.style.display='none';
    }
    // Label the original release summary as historical until actual current binaries exist.
    const oldHeading=Array.from(section.querySelectorAll('h3')).find(x=>x.textContent?.trim()==='Release');
    if(oldHeading) oldHeading.textContent='Previous Windows release (historical)';
    return true;
  }
  if(!mount()) {
    const ob=new MutationObserver(()=>{if(mount())ob.disconnect()});
    ob.observe(document.documentElement,{childList:true,subtree:true});
    window.addEventListener('load',()=>{mount();ob.disconnect();},{once:true});
  }
})();

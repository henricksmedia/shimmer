// master-view.js — Master screen state controller.
// Switches between the hero empty state and the 3-zone working layout,
// fills the rail session card, and lists real recent sessions from
// /api/projects.  Purely observational: it watches signals single.js
// already emits (process-btn enabling on file adoption, auto-detect
// results unhiding, done-banner unhiding) so single.js needs no changes.

export function initMasterView() {
    const emptyEl    = document.getElementById('master-empty');
    const workEl     = document.getElementById('master-work');
    const dropzone   = document.getElementById('dropzone');
    const dzSlot     = document.getElementById('dropzone-slot');
    const processBtn = document.getElementById('process-btn');
    const selected   = document.getElementById('selected-file');
    const results    = document.getElementById('auto-detect-results');
    const banner     = document.getElementById('done-banner');
    const hint       = document.getElementById('analysis-hint');
    const session    = document.getElementById('session-card');
    if (!emptyEl || !workEl || !processBtn) return;

    let loaded = false;

    function sync() {
        const hasFile = !processBtn.disabled || (banner && !banner.hidden);
        if (hasFile && !loaded) {
            loaded = true;
            // Move the live dropzone (listeners intact) into the left
            // column as a compact re-drop target.
            dzSlot.appendChild(dropzone);
            dropzone.classList.add('dropzone-compact');
            emptyEl.hidden = true;
            workEl.hidden = false;
        }
        if (hint && results) hint.hidden = !results.hidden;
        syncSession();
    }

    function syncSession() {
        if (!session) return;
        const name = (selected?.textContent || '').trim();
        if (!loaded || !name) { session.classList.remove('visible'); return; }
        session.classList.add('visible');
        session.querySelector('.fname').textContent = name;
        // Long names ellipsize in the chip — full name on hover.
        if (selected && !selected.title) selected.title = name;
        if (selected && selected.title !== name) selected.title = name;
        const badges = [];
        if (results && !results.hidden) badges.push('<span class="chip cyan">analyzed</span>');
        if (banner && !banner.hidden) badges.push('<span class="chip ok">✓ processed</span>');
        session.querySelector('.badge-row').innerHTML = badges.join('');
    }

    const obs = new MutationObserver(sync);
    obs.observe(processBtn, { attributes: true, attributeFilter: ['disabled'] });
    if (selected) obs.observe(selected, { attributes: true, attributeFilter: ['hidden'], childList: true, subtree: true, characterData: true });
    if (results) obs.observe(results, { attributes: true, attributeFilter: ['hidden'] });
    if (banner) obs.observe(banner, { attributes: true, attributeFilter: ['hidden'] });
    sync();
}

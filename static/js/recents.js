// recents.js — clickable Recent sessions with real file restore.
//
// Browsers never expose a dropped file's path, so a plain "path in
// localStorage" is impossible.  Chromium's File System Access API is the
// sanctioned mechanism: FileSystemFileHandles are structured-cloneable,
// so we persist them in IndexedDB and reopen the file later after a
// one-click permission re-grant (which requires a user gesture — the
// click on the recent item itself).
//
// Capture points:
//  - window drop (capture phase): grab the handle via
//    DataTransferItem.getAsFileSystemHandle() without disturbing the
//    tabs' own drop handling.
//  - "Choose file…" on either tab: intercepted in capture phase to use
//    showOpenFilePicker() (which yields a handle), falling back to the
//    native <input> when the API is missing or the user cancels.
// Files that arrive without a handle still get a recents row — they just
// say "re-drop the file to restore" instead of being clickable.
//
// Both tabs list the same sessions: Master's list adopts into Master,
// the Remix list into Remix. Rows whose stems are already separated
// (the server's stem library, matched by the content digest the upload
// reported) carry a "stems ready" badge.

const DB_NAME = 'shimmer-ui';
const STORE = 'recents';
const MAX_RECENTS = 6;

// Each list: where it renders and which <input type=file> it feeds.
const LISTS = [
    { card: 'recents-card', list: 'recents-list', input: 'file-input', pick: 'pick-file-btn' },
    { card: 'remix-recents-card', list: 'remix-recents-list', input: 'remix-file-input', pick: 'remix-pick-btn' },
];

let stemLibrary = null;   // digest -> {models, tiers}; null until fetched

function openDb() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'key' });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

function tx(db, mode, fn) {
    return new Promise((resolve, reject) => {
        const t = db.transaction(STORE, mode);
        const out = fn(t.objectStore(STORE));
        t.oncomplete = () => resolve(out?.result !== undefined ? out.result : out);
        t.onerror = () => reject(t.error);
    });
}

function recKey(file) { return `${file.name}|${file.size}`; }

async function getRecord(db, key) {
    return new Promise((res) => {
        const t = db.transaction(STORE, 'readonly');
        const q = t.objectStore(STORE).get(key);
        q.onsuccess = () => res(q.result);
        q.onerror = () => res(null);
    });
}

async function saveRecent(file, handle = null) {
    try {
        const db = await openDb();
        const key = recKey(file);
        const prev = await getRecord(db, key);
        const rec = { key, name: file.name, size: file.size, ts: Date.now() };
        if (handle) rec.handle = handle;   // FileSystemFileHandle is cloneable
        else if (prev?.handle) rec.handle = prev.handle;   // keep an existing handle
        if (prev?.digest) rec.digest = prev.digest;
        await tx(db, 'readwrite', (s) => s.put(rec));
        // Trim to the newest MAX_RECENTS.
        const all = await listRecents();
        for (const extra of all.slice(MAX_RECENTS)) {
            await tx(db, 'readwrite', (s) => s.delete(extra.key));
        }
        renderRecents();
    } catch (_) { /* IndexedDB unavailable — recents just stay empty */ }
}

// The upload told us the file's content digest: keep it on the row so
// the stems badge can match the server's library.
async function noteDigest(name, size, digest) {
    if (!digest) return;
    try {
        const db = await openDb();
        const key = `${name}|${size}`;
        const prev = await getRecord(db, key);
        if (!prev || prev.digest === digest) return;
        await tx(db, 'readwrite', (s) => s.put({ ...prev, digest }));
        renderRecents();
    } catch (_) { /* best-effort */ }
}

async function listRecents() {
    const db = await openDb();
    const rows = await new Promise((resolve, reject) => {
        const t = db.transaction(STORE, 'readonly');
        const q = t.objectStore(STORE).getAll();
        q.onsuccess = () => resolve(q.result || []);
        q.onerror = () => reject(q.error);
    });
    return rows.sort((a, b) => b.ts - a.ts);
}

async function loadStemLibrary() {
    try {
        const res = await fetch('/api/stems/library');
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        stemLibrary = {};
        for (const item of data.items || []) stemLibrary[item.digest] = item;
    } catch (_) {
        stemLibrary = stemLibrary || {};
    }
}

function adoptInto(inputId, file) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
}

async function restore(rec, rowEl, inputId) {
    const errEl = rowEl.querySelector('.r-err');
    errEl.textContent = '';
    if (!rec.handle) {
        errEl.textContent = 'no saved handle — re-drop the file';
        return;
    }
    try {
        let perm = await rec.handle.queryPermission({ mode: 'read' });
        if (perm !== 'granted') perm = await rec.handle.requestPermission({ mode: 'read' });
        if (perm !== 'granted') { errEl.textContent = 'permission declined'; return; }
        const file = await rec.handle.getFile();
        adoptInto(inputId, file);
    } catch (e) {
        errEl.textContent = 'couldn’t reopen (moved or deleted?) — re-drop the file';
    }
}

const TIER_LABELS = { fast: 'Fast', best: 'Best', six: '6 stems' };

function stemsBadge(rec) {
    if (!rec.digest || !stemLibrary) return '';
    const item = stemLibrary[rec.digest];
    if (!item) return '';
    const tiers = (item.tiers || []).map(k => TIER_LABELS[k] || k);
    const title = tiers.length ? `Stems already separated: ${tiers.join(', ')}` : 'Stems already separated';
    return `<span class="chip r-stems" title="${title}">stems ready</span>`;
}

export async function renderRecents() {
    let rows = [];
    try { rows = (await listRecents()).slice(0, MAX_RECENTS); } catch (_) { return; }
    if (stemLibrary === null) await loadStemLibrary();
    for (const spec of LISTS) {
        const card = document.getElementById(spec.card);
        const list = document.getElementById(spec.list);
        if (!card || !list) continue;
        if (!rows.length) { card.hidden = true; continue; }
        list.innerHTML = rows.map((r, i) => `
            <button type="button" class="recent-item" data-i="${i}" title="${r.handle ? 'Click to reload this file' : 'Re-drop the file to load it again'}">
                <span class="r-note">♪</span>
                <span class="r-name">${escapeHtml(r.name)}</span>
                ${stemsBadge(r)}
                <span class="r-err"></span>
                <span class="r-hint">${(r.size / 1e6).toFixed(1)} MB · ${r.handle ? 'click to reload' : 're-drop to restore'}</span>
            </button>`).join('');
        list.querySelectorAll('.recent-item').forEach((btn) =>
            btn.addEventListener('click', () => restore(rows[+btn.dataset.i], btn, spec.input)));
        card.hidden = false;
    }
}

export function initRecents() {
    // 1. Record every adoption (with or without a handle), on both tabs.
    for (const spec of LISTS) {
        const input = document.getElementById(spec.input);
        input?.addEventListener('change', () => {
            const f = input.files && input.files[0];
            if (f) saveRecent(f);
        });
    }

    // 2. Drops: capture the file handle alongside the tabs' own handling.
    window.addEventListener('drop', (e) => {
        const item = e.dataTransfer?.items?.[0];
        if (!item || item.kind !== 'file' || !item.getAsFileSystemHandle) return;
        const file = item.getAsFile();
        item.getAsFileSystemHandle().then((h) => {
            if (h?.kind === 'file' && file) saveRecent(file, h);
        }).catch(() => {});
    }, true);

    // 3. "Choose file…": prefer showOpenFilePicker so we get a handle.
    if (window.showOpenFilePicker) {
        for (const spec of LISTS) {
            const pickBtn = document.getElementById(spec.pick);
            if (!pickBtn) continue;
            pickBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();   // keep the tab from also opening <input>
                try {
                    const [handle] = await window.showOpenFilePicker({
                        types: [{
                            description: 'Audio',
                            accept: { 'audio/*': ['.wav', '.mp3', '.flac', '.ogg', '.m4a'] },
                        }],
                    });
                    const file = await handle.getFile();
                    await saveRecent(file, handle);
                    adoptInto(spec.input, file);
                } catch (err) {
                    if (err?.name === 'AbortError') return;      // user cancelled
                    document.getElementById(spec.input)?.click();  // fallback
                }
            }, true);
        }
    }

    // 4. Uploads report the content digest; stems finishing may add a set
    //    to the library. Both refresh the badges.
    document.addEventListener('shimmer:uploaded', (e) => {
        const d = e.detail || {};
        if (d.digest && Array.isArray(d.stems_tiers) && d.stems_tiers.length && stemLibrary) {
            stemLibrary[d.digest] = { digest: d.digest, tiers: d.stems_tiers, models: [] };
        }
        noteDigest(d.name, d.size, d.digest);
    });
    document.addEventListener('shimmer:stems-ready', async () => {
        await loadStemLibrary();
        renderRecents();
    });

    renderRecents();
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}
